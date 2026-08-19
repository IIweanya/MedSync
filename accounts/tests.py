"""Tests for the accounts app: signup, email verification, login gating, resend
rate limiting, password reset, and the phone-number round trip.

Covers the checklist in req1 §14. Django's test runner swaps in the locmem email
backend automatically, so `mail.outbox` captures what would have been sent without
touching Brevo or any other provider.
"""

import re
from datetime import timedelta

from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User, DoctorProfile, PatientProfile, EmailVerification, PasswordResetToken
from .tokens import email_verification_token, encode_uid

# Strong enough for Django's validators and dissimilar to the test emails/names, so
# a failure means the code is wrong rather than the password being rejected.
PASSWORD = 'Str0ng-Tulip-9142'
NEW_PASSWORD = 'An0ther-Maple-7731'

VERIFY_URL_RE = re.compile(r'https?://[^/\s]+(/accounts/verify-email/[^\s]+/)')


def doctor_signup_data(**overrides):
    data = {
        'full_name': 'Jane Smith',
        'email': 'jane.smith@example.com',
        'country_code': 'NG',
        'phone': '8012345678',
        'specialty': 'cardiology',
        'license_id': 'MD-123456',
        'password': PASSWORD,
        'password2': PASSWORD,
        'agree_terms': 'on',
    }
    data.update(overrides)
    return data


def patient_signup_data(**overrides):
    data = {
        'full_name': 'Chris Baker',
        'email': 'chris.baker@example.com',
        'country_code': 'GB',
        'phone': '7700900123',
        'date_of_birth': '1990-04-17',
        'password': PASSWORD,
        'password2': PASSWORD,
        'agree_terms': 'on',
    }
    data.update(overrides)
    return data


def extract_verify_path(message):
    """Pull the verification path out of a sent email's plain-text body."""
    match = VERIFY_URL_RE.search(message.body)
    assert match, f'No verification URL found in email body:\n{message.body}'
    return match.group(1)


def encode_uid_for_pk(pk):
    """uidb64 for an arbitrary pk, including ones with no user behind them."""
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    return urlsafe_base64_encode(force_bytes(pk))


class DoctorSignupVerificationFlowTests(TestCase):
    """Signup -> email -> verify -> login -> dashboard, for a doctor."""

    def test_full_flow(self):
        response = self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        # Signup grants immediate access — verification gates sign-in, not signup.
        self.assertRedirects(response, reverse('doctor_dashboard'))

        user = User.objects.get(email='jane.smith@example.com')
        self.assertEqual(user.role, User.DOCTOR)
        self.assertFalse(user.is_verified, 'a new account is still unverified')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertTrue(DoctorProfile.objects.filter(user=user).exists())

        # The link is still sent at signup, ready for their next sign-in.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Verify your MedSync email address')
        self.assertEqual(mail.outbox[0].to, [user.email])

        # Opening it verifies and lands on the dashboard.
        verify_response = self.client.get(extract_verify_path(mail.outbox[0]))
        self.assertRedirects(verify_response, reverse('doctor_dashboard'))
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_signup_reaches_the_dashboard_without_verifying(self):
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        self.assertEqual(self.client.get(reverse('doctor_dashboard')).status_code, 200)
        self.assertFalse(User.objects.get(email='jane.smith@example.com').is_verified)

    def test_signup_stores_the_country(self):
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        self.assertEqual(User.objects.get(email='jane.smith@example.com').country, 'NG')

    def test_email_body_contains_no_password(self):
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        body = mail.outbox[0].body
        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn(PASSWORD, body)
        self.assertNotIn(PASSWORD, html)

    def test_verification_email_has_html_alternative(self):
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        message = mail.outbox[0]
        self.assertEqual(len(message.alternatives), 1)
        self.assertEqual(message.alternatives[0][1], 'text/html')
        # Fallback URL must appear in the plain-text part too (req1 §4).
        self.assertIn('/accounts/verify-email/', message.body)


class PatientSignupVerificationFlowTests(TestCase):
    """The same mechanism must work for patients (req1 §12)."""

    def test_full_flow(self):
        response = self.client.post(reverse('accounts:patient_signup'), patient_signup_data())
        self.assertRedirects(response, reverse('patient_dashboard'))

        user = User.objects.get(email='chris.baker@example.com')
        self.assertEqual(user.role, User.PATIENT)
        self.assertFalse(user.is_verified)
        self.assertEqual(user.country, 'GB')
        self.assertTrue(PatientProfile.objects.filter(user=user).exists())

        verify_response = self.client.get(extract_verify_path(mail.outbox[0]))
        self.assertRedirects(verify_response, reverse('patient_dashboard'))
        user.refresh_from_db()
        self.assertTrue(user.is_verified)


class VerificationTokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='token@example.com', full_name='Token Tester',
            role=User.PATIENT, password=PASSWORD,
        )
        PatientProfile.objects.create(user=self.user)

    def verify_url(self, token=None, uidb64=None):
        return reverse('accounts:verify_email', kwargs={
            'uidb64': uidb64 or encode_uid(self.user),
            'token': token or email_verification_token.make_token(self.user),
        })

    def test_valid_token_verifies_and_signs_in(self):
        response = self.client.get(self.verify_url())
        self.assertRedirects(response, reverse('patient_dashboard'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_invalid_token_is_rejected(self):
        response = self.client.get(self.verify_url(token='not-a-real-token'))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'expired or invalid', status_code=400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_verified)

    def test_malformed_uid_is_rejected_without_error(self):
        """A junk uid must render the friendly page, not raise (req1 §5)."""
        response = self.client.get(self.verify_url(uidb64='!!!not-base64!!!'))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'expired or invalid', status_code=400)

    def test_non_numeric_uid_is_rejected_without_error(self):
        """'YWJj' base64-decodes cleanly to 'abc'. Passing that straight to a pk
        lookup would raise ValueError from the field and return a 500."""
        response = self.client.get(self.verify_url(uidb64='YWJj'))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'expired or invalid', status_code=400)

    def test_unknown_user_is_rejected(self):
        response = self.client.get(self.verify_url(uidb64=encode_uid_for_pk(999999)))
        self.assertEqual(response.status_code, 400)

    def test_expired_verification_is_rejected(self):
        verification = EmailVerification.objects.create(user=self.user)
        EmailVerification.objects.filter(pk=verification.pk).update(
            created_at=timezone.now() - timedelta(hours=25),
            last_sent_at=timezone.now() - timedelta(hours=25),
        )
        response = self.client.get(self.verify_url())
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, 'expired or invalid', status_code=410)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_verified)

    def test_already_verified_redirects_to_login(self):
        url = self.verify_url()
        self.client.get(url)
        fresh = Client()
        response = fresh.get(url)
        self.assertRedirects(response, reverse('accounts:patient_login'))

    def test_already_verified_link_does_not_sign_anyone_in(self):
        """The already-verified branch runs *before* the token is checked, and
        uidb64 is just base64 of the primary key. If it signed users in, anyone
        could hijack any verified account by walking uids."""
        self.user.is_verified = True
        self.user.save(update_fields=['is_verified'])

        fresh = Client()
        # A deliberately bogus token: only the (guessable) uid is real.
        response = fresh.get(self.verify_url(token='made-up-token'))
        self.assertRedirects(response, reverse('accounts:patient_login'))
        self.assertNotIn('_auth_user_id', fresh.session)

    def test_token_is_single_use(self):
        """Verifying flips is_verified, which is part of the token hash — so the
        same token can no longer authenticate a fresh verification."""
        token = email_verification_token.make_token(self.user)
        self.assertTrue(email_verification_token.check_token(self.user, token))
        self.user.is_verified = True
        self.user.save(update_fields=['is_verified'])
        self.user.refresh_from_db()
        self.assertFalse(email_verification_token.check_token(self.user, token))

    def test_changing_email_invalidates_token(self):
        token = email_verification_token.make_token(self.user)
        self.user.email = 'moved@example.com'
        self.user.save(update_fields=['email'])
        self.assertFalse(email_verification_token.check_token(self.user, token))

    def test_reset_token_is_not_accepted_for_verification(self):
        """Distinct key_salt means the two token types are not interchangeable."""
        from django.contrib.auth.tokens import default_token_generator
        reset_token = default_token_generator.make_token(self.user)
        self.assertFalse(email_verification_token.check_token(self.user, reset_token))


class UnverifiedLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='unverified@example.com', full_name='Un Verified',
            role=User.DOCTOR, password=PASSWORD,
        )
        DoctorProfile.objects.create(user=self.user, specialty='general', license_id='X-1')

    def test_correct_password_but_unverified_is_blocked(self):
        response = self.client.post(reverse('accounts:doctor_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })
        self.assertRedirects(response, reverse('accounts:verify_email_required'))
        # No login session was created.
        self.assertNotIn('_auth_user_id', self.client.session)

        page = self.client.get(reverse('accounts:verify_email_required'))
        self.assertContains(page, 'Verify your email')
        self.assertContains(page, self.user.email)

    def test_signing_in_unverified_sends_a_fresh_link(self):
        """Signing in is enough to get a usable email — the user should not have to
        know to press "resend"."""
        self.assertEqual(len(mail.outbox), 0)
        self.client.post(reverse('accounts:doctor_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(mail.outbox[0].subject, 'Verify your MedSync email address')

    def test_repeated_sign_in_attempts_do_not_flood_the_inbox(self):
        """The auto-send respects the same throttle as an explicit resend, so the
        login form can't be used as an unlimited mailer."""
        for _ in range(4):
            self.client.post(reverse('accounts:doctor_login'), {
                'email': self.user.email, 'password': PASSWORD,
            })
        self.assertEqual(len(mail.outbox), 1, 'cooldown should suppress the repeats')

    def test_blocking_page_starts_the_resend_countdown(self):
        self.client.post(reverse('accounts:doctor_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })
        page = self.client.get(reverse('accounts:verify_email_required'))
        self.assertGreater(page.context['retry_after'], 0)
        # The button carries the remaining seconds for the client-side countdown.
        self.assertContains(page, 'data-retry-after=')

    def test_verified_link_from_login_flow_lands_on_the_dashboard(self):
        self.client.post(reverse('accounts:doctor_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })
        response = self.client.get(extract_verify_path(mail.outbox[0]))
        self.assertRedirects(response, reverse('doctor_dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_unverified_user_cannot_reach_dashboard(self):
        self.client.post(reverse('accounts:doctor_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })
        response = self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_required_page_without_session_redirects(self):
        response = self.client.get(reverse('accounts:verify_email_required'))
        self.assertRedirects(response, reverse('accounts:login'))

    def test_wrong_password_gives_generic_error(self):
        response = self.client.post(reverse('accounts:doctor_login'), {
            'email': self.user.email, 'password': 'wrong-password',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid email or password')

    def test_unknown_email_gives_the_same_generic_error(self):
        """Identical wording for unknown address and wrong password, so the form
        cannot be used to discover which addresses are registered (req1 §6)."""
        response = self.client.post(reverse('accounts:doctor_login'), {
            'email': 'nobody@example.com', 'password': PASSWORD,
        })
        self.assertContains(response, 'Invalid email or password')

    def test_wrong_role_gives_the_same_generic_error(self):
        """A doctor's credentials on the patient form must not confirm the account
        exists as a doctor."""
        response = self.client.post(reverse('accounts:patient_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })
        self.assertContains(response, 'Invalid email or password')


class ResendVerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='resend@example.com', full_name='Re Send',
            role=User.PATIENT, password=PASSWORD,
        )
        PatientProfile.objects.create(user=self.user)

    def start_unverified_session(self):
        """Sign in with the right password. This sets the session marker and, as of
        the auto-send behaviour, also dispatches one verification email."""
        self.client.post(reverse('accounts:patient_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })

    def clear_cooldown(self):
        """Push the last send past the cooldown so an explicit resend is allowed."""
        EmailVerification.objects.filter(user=self.user).update(
            last_sent_at=timezone.now() - timedelta(
                seconds=EmailVerification.RESEND_COOLDOWN_SECONDS + 5),
        )

    def test_resend_from_blocking_page_sends(self):
        self.start_unverified_session()
        self.clear_cooldown()
        mail.outbox.clear()
        response = self.client.post(reverse('accounts:resend_verification'))
        self.assertRedirects(response, reverse('accounts:verify_email_required'))
        self.assertEqual(len(mail.outbox), 1)

    def test_cooldown_blocks_immediate_second_request(self):
        # The sign-in itself sends one and starts the cooldown.
        self.start_unverified_session()
        mail.outbox.clear()
        self.client.post(reverse('accounts:resend_verification'))
        self.assertEqual(len(mail.outbox), 0, 'cooldown should suppress the second send')

    def test_hourly_quota_blocks_further_requests(self):
        self.start_unverified_session()
        verification, _ = EmailVerification.objects.get_or_create(user=self.user)
        # Past the 60s cooldown, but already at the hourly cap.
        EmailVerification.objects.filter(pk=verification.pk).update(
            resend_count=EmailVerification.RESEND_MAX,
            resend_window_started_at=timezone.now() - timedelta(minutes=5),
            last_sent_at=timezone.now() - timedelta(minutes=5),
        )
        mail.outbox.clear()
        self.client.post(reverse('accounts:resend_verification'))
        self.assertEqual(len(mail.outbox), 0, 'hourly quota should suppress the send')

    def test_quota_resets_after_the_window(self):
        self.start_unverified_session()
        verification, _ = EmailVerification.objects.get_or_create(user=self.user)
        EmailVerification.objects.filter(pk=verification.pk).update(
            resend_count=EmailVerification.RESEND_MAX,
            resend_window_started_at=timezone.now() - timedelta(hours=2),
            last_sent_at=timezone.now() - timedelta(hours=2),
        )
        mail.outbox.clear()
        self.client.post(reverse('accounts:resend_verification'))
        self.assertEqual(len(mail.outbox), 1)

    def test_anonymous_resend_does_not_reveal_account_existence(self):
        url = reverse('accounts:resend_verification')

        known = self.client.post(url, {'email': self.user.email}, follow=True)
        known_sent = len(mail.outbox)
        mail.outbox.clear()

        unknown = self.client.post(url, {'email': 'nobody@example.com'}, follow=True)
        unknown_sent = len(mail.outbox)

        self.assertEqual(known_sent, 1)
        self.assertEqual(unknown_sent, 0, 'nothing should be sent for an unknown address')
        # The user-visible outcome is identical either way.
        self.assertContains(known, 'If an account exists for that email address')
        self.assertContains(unknown, 'If an account exists for that email address')

    def test_anonymous_resend_ignores_already_verified_accounts(self):
        self.user.is_verified = True
        self.user.save(update_fields=['is_verified'])
        mail.outbox.clear()
        response = self.client.post(
            reverse('accounts:resend_verification'),
            {'email': self.user.email}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, 'If an account exists for that email address')


class ChangeEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='typo@example.com', full_name='Ty Po',
            role=User.PATIENT, password=PASSWORD,
        )
        PatientProfile.objects.create(user=self.user)
        self.client.post(reverse('accounts:patient_login'), {
            'email': self.user.email, 'password': PASSWORD,
        })

    def test_change_email_updates_and_resends(self):
        mail.outbox.clear()
        response = self.client.post(reverse('accounts:change_email'),
                                    {'email': 'correct@example.com'})
        self.assertRedirects(response, reverse('accounts:verify_email_sent'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'correct@example.com')
        self.assertFalse(self.user.is_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['correct@example.com'])

    def test_cannot_take_an_existing_address(self):
        User.objects.create_user(email='taken@example.com', full_name='Taken',
                                 role=User.PATIENT, password=PASSWORD)
        response = self.client.post(reverse('accounts:change_email'),
                                    {'email': 'taken@example.com'})
        self.assertContains(response, 'An account with this email already exists')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'typo@example.com')

    def test_requires_an_unverified_session(self):
        """A visitor with no proven password must not reach the change-email form."""
        fresh = Client()
        response = fresh.get(reverse('accounts:change_email'))
        self.assertRedirects(response, reverse('accounts:login'))


class SignupValidationTests(TestCase):
    def test_duplicate_email_is_reported(self):
        User.objects.create_user(email='jane.smith@example.com', full_name='Existing',
                                 role=User.DOCTOR, password=PASSWORD)
        response = self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'An account with this email already exists.')
        self.assertEqual(User.objects.filter(email='jane.smith@example.com').count(), 1)

    def test_duplicate_email_is_case_insensitive(self):
        User.objects.create_user(email='jane.smith@example.com', full_name='Existing',
                                 role=User.DOCTOR, password=PASSWORD)
        response = self.client.post(
            reverse('accounts:doctor_signup'),
            doctor_signup_data(email='Jane.Smith@Example.com'),
        )
        self.assertContains(response, 'An account with this email already exists.')

    def test_doctor_email_cannot_be_reused_for_a_patient(self):
        """One address, one account, regardless of role — enforced by the single
        User table with a unique email, so there is no per-role namespace."""
        User.objects.create_user(email='shared@example.com', full_name='The Doctor',
                                 role=User.DOCTOR, password=PASSWORD)
        response = self.client.post(
            reverse('accounts:patient_signup'),
            patient_signup_data(email='shared@example.com'),
        )
        self.assertContains(response, 'An account with this email already exists.')
        self.assertEqual(User.objects.filter(email='shared@example.com').count(), 1)
        self.assertEqual(User.objects.get(email='shared@example.com').role, User.DOCTOR)

    def test_patient_email_cannot_be_reused_for_a_doctor(self):
        User.objects.create_user(email='shared@example.com', full_name='The Patient',
                                 role=User.PATIENT, password=PASSWORD)
        response = self.client.post(
            reverse('accounts:doctor_signup'),
            doctor_signup_data(email='shared@example.com'),
        )
        self.assertContains(response, 'An account with this email already exists.')
        self.assertEqual(User.objects.get(email='shared@example.com').role, User.PATIENT)

    def test_invalid_email_is_reported(self):
        response = self.client.post(reverse('accounts:doctor_signup'),
                                    doctor_signup_data(email='not-an-email'))
        self.assertContains(response, 'Enter a valid email address')
        self.assertFalse(User.objects.filter(full_name='Jane Smith').exists())

    def test_password_mismatch_is_reported(self):
        response = self.client.post(reverse('accounts:doctor_signup'),
                                    doctor_signup_data(password2='Different-Pass-1234'))
        self.assertContains(response, 'Passwords do not match.')

    def test_terms_must_be_accepted(self):
        data = doctor_signup_data()
        del data['agree_terms']
        response = self.client.post(reverse('accounts:doctor_signup'), data)
        self.assertContains(response, 'Please accept the Terms of Service')

    def test_no_account_is_created_when_validation_fails(self):
        self.client.post(reverse('accounts:doctor_signup'),
                         doctor_signup_data(password2='mismatch'))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)


class PhoneNumberTests(TestCase):
    """Guards the double-prefix regression: the dial code must be applied exactly
    once, server-side, no matter how many times the form is submitted."""

    def test_dial_code_is_combined_once(self):
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        user = User.objects.get(email='jane.smith@example.com')
        self.assertEqual(user.phone, '+2348012345678')

    def test_country_choice_survives_a_validation_error(self):
        """After a failed submit the select must still show the chosen country and
        the input must still hold the *national* number, un-prefixed."""
        response = self.client.post(
            reverse('accounts:doctor_signup'),
            doctor_signup_data(country_code='NG', password2='mismatch'),
        )
        self.assertContains(response, 'value="NG" selected')
        self.assertContains(response, 'value="8012345678"')
        self.assertNotContains(response, 'value="+2348012345678"')

    def test_resubmitting_after_an_error_does_not_double_prefix(self):
        data = doctor_signup_data(password2='mismatch')
        self.client.post(reverse('accounts:doctor_signup'), data)
        # Second attempt with the error corrected, same phone input as before.
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data())
        user = User.objects.get(email='jane.smith@example.com')
        self.assertEqual(user.phone, '+2348012345678')
        self.assertNotIn('+234+234', user.phone)

    def test_formatted_input_is_normalised(self):
        self.client.post(reverse('accounts:doctor_signup'),
                         doctor_signup_data(country_code='US', phone='(816) 762-3556'))
        user = User.objects.get(email='jane.smith@example.com')
        self.assertEqual(user.phone, '+18167623556')

    def test_too_short_number_is_rejected(self):
        response = self.client.post(reverse('accounts:doctor_signup'),
                                    doctor_signup_data(phone='123'))
        self.assertContains(response, 'looks too short')

    def test_invalid_country_is_rejected(self):
        response = self.client.post(reverse('accounts:doctor_signup'),
                                    doctor_signup_data(country_code='ZZ'))
        self.assertContains(response, 'Please choose a valid country.')

    def test_phone_is_optional(self):
        self.client.post(reverse('accounts:doctor_signup'), doctor_signup_data(phone=''))
        user = User.objects.get(email='jane.smith@example.com')
        self.assertEqual(user.phone, '')


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='reset@example.com', full_name='Re Set',
            role=User.PATIENT, password=PASSWORD, is_verified=True,
        )
        PatientProfile.objects.create(user=self.user)

    def test_full_reset_flow(self):
        response = self.client.post(reverse('accounts:forgot_password'),
                                    {'email': self.user.email}, follow=True)
        self.assertContains(response, 'If an account exists for that email address')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Reset your MedSync password')

        token = PasswordResetToken.objects.get(user=self.user)
        reset_url = reverse('accounts:reset_password', kwargs={'token': token.token})
        self.assertEqual(self.client.get(reset_url).status_code, 200)

        self.client.post(reset_url, {'password': NEW_PASSWORD, 'password2': NEW_PASSWORD})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

        login_response = self.client.post(reverse('accounts:patient_login'), {
            'email': self.user.email, 'password': NEW_PASSWORD,
        })
        self.assertRedirects(login_response, reverse('patient_dashboard'))

    def test_unknown_email_gives_the_same_response_and_sends_nothing(self):
        response = self.client.post(reverse('accounts:forgot_password'),
                                    {'email': 'nobody@example.com'}, follow=True)
        self.assertContains(response, 'If an account exists for that email address')
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_email_never_contains_a_password(self):
        self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email})
        self.assertNotIn(PASSWORD, mail.outbox[0].body)
        self.assertNotIn(PASSWORD, mail.outbox[0].alternatives[0][0])

    def test_expired_token_is_rejected(self):
        token = PasswordResetToken.objects.create(user=self.user)
        PasswordResetToken.objects.filter(pk=token.pk).update(
            created_at=timezone.now() - timedelta(hours=2),
        )
        response = self.client.get(
            reverse('accounts:reset_password', kwargs={'token': token.token}))
        self.assertRedirects(response, reverse('accounts:forgot_password'))

    def test_token_cannot_be_reused(self):
        token = PasswordResetToken.objects.create(user=self.user)
        url = reverse('accounts:reset_password', kwargs={'token': token.token})
        self.client.post(url, {'password': NEW_PASSWORD, 'password2': NEW_PASSWORD})
        # Second attempt: the token is spent, so the URL no longer resolves to it.
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_role_scoped_forgot_password_pages_render(self):
        for name in ('accounts:doctor_forgot_password', 'accounts:patient_forgot_password'):
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class LegacyVerificationLinkTests(TestCase):
    """Links issued before signed tokens must keep working (no dead links in
    anyone's inbox)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='legacy@example.com', full_name='Le Gacy',
            role=User.PATIENT, password=PASSWORD,
        )
        PatientProfile.objects.create(user=self.user)

    def test_legacy_uuid_link_verifies(self):
        verification = EmailVerification.objects.create(user=self.user)
        response = self.client.get(reverse('accounts:verify_email_legacy',
                                           kwargs={'token': verification.token}))
        self.assertRedirects(response, reverse('patient_dashboard'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)

    def test_unknown_legacy_token_is_rejected(self):
        import uuid
        response = self.client.get(reverse('accounts:verify_email_legacy',
                                           kwargs={'token': uuid.uuid4()}))
        self.assertEqual(response.status_code, 400)


class PageSmokeTests(TestCase):
    """Every public and auth page must render. The design-system fix in base.html
    affects all of them, so a template error anywhere should fail the suite."""

    def test_public_and_auth_pages_render(self):
        names = [
            'core:landing', 'core:about', 'core:how_it_works', 'core:contact', 'core:faq',
            'accounts:login', 'accounts:doctor_login', 'accounts:doctor_signup',
            'accounts:patient_login', 'accounts:patient_signup',
            'accounts:forgot_password', 'accounts:doctor_forgot_password',
            'accounts:patient_forgot_password', 'accounts:resend_verification',
        ]
        for name in names:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200, f'{name} did not render')

    def test_contact_form_delivers(self):
        response = self.client.post(reverse('core:contact'), {
            'name': 'Ada Byron',
            'email': 'ada@example.com',
            'subject': 'general',
            'message': 'I have a question about booking an appointment.',
        }, follow=True)
        self.assertContains(response, 'Thanks for getting in touch')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, ['ada@example.com'])

    def test_contact_form_rejects_a_short_message(self):
        response = self.client.post(reverse('core:contact'), {
            'name': 'Ada Byron',
            'email': 'ada@example.com',
            'subject': 'general',
            'message': 'hi',
        })
        self.assertContains(response, 'a little more detail')
        self.assertEqual(len(mail.outbox), 0)

from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.urls import reverse

from .emails import send_password_reset_email, send_verification_email
from .models import User, EmailVerification, PasswordResetToken
from .tokens import decode_uid, email_verification_token
from .forms import (
    DoctorSignUpForm, PatientSignUpForm, ForgotPasswordForm, LoginForm,
    ResetPasswordForm, ResendVerificationForm, ChangeEmailForm,
    DoctorProfileForm, PatientProfileForm, ChangePasswordForm,
)

# Session keys.
#: Address the "check your email" page should display, set at signup.
PENDING_EMAIL_KEY = 'pending_verification_email'
#: Set only after a *correct* password for an unverified account. Acts as proof of
#: password ownership for the resend / change-email actions on the blocking page,
#: without granting a real login session.
UNVERIFIED_USER_KEY = 'unverified_user_id'

#: Shown by every anonymous endpoint that takes an email address, whether or not
#: the address is registered (req1 §7, §11).
GENERIC_EMAIL_SENT = (
    'If an account exists for that email address, a new verification email has been sent.'
)
GENERIC_RESET_SENT = (
    'If an account exists for that email address, a password reset link has been sent.'
)
SEND_FAILED = (
    'We could not send the email just now. Please try again in a few minutes.'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issue_verification(user, request, respect_throttle=True):
    """Send (or resend) a verification email.

    Returns one of 'sent', 'throttled', 'failed'. The throttle state lives on the
    user's EmailVerification row, so it survives a server restart — unlike a
    cache-based counter with the default in-memory backend.
    """
    verification, _ = EmailVerification.objects.get_or_create(user=user)

    if respect_throttle:
        allowed, _reason = verification.can_resend()
        if not allowed:
            return 'throttled'

    if not send_verification_email(user, request):
        return 'failed'

    verification.mark_sent()
    return 'sent'


def _signup(request, form_class, template, icon_context):
    """Shared signup handling for both roles.

    Signing up grants immediate dashboard access — verification is enforced at
    *sign-in*, not at registration. The link still goes out now so it is waiting in
    the inbox before the user's next sign-in, which is the point at which a missing
    verification starts to block them.

    Only the form class, template and copy differ per role; account creation, token
    issue and redirect are identical (req1 §12).
    """
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            user = form.save()
            outcome = _issue_verification(user, request, respect_throttle=False)

            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            if outcome == 'failed':
                messages.warning(
                    request,
                    'Your account is ready, but we could not send the verification '
                    'email. You can request another one from the sign-in page — '
                    "you'll need a verified address next time you sign in.",
                )
            else:
                messages.success(
                    request,
                    f'Welcome to MedSync, {user.display_name}! We sent a verification '
                    f'link to {user.email} — please confirm it, as you will need a '
                    'verified address to sign in again.',
                )
            return redirect(_dashboard_url_for(user))
    else:
        form = form_class()
    return render(request, template, {'form': form, **icon_context})


def _login(request, role, template, dashboard_url_name, context):
    """Shared login handling for both roles."""
    form = LoginForm(request.POST or None, request=request, role=role)
    if request.method == 'POST' and form.is_valid():
        user = form.user
        if not user.is_verified:
            # Correct password, unverified address: no login session, no dashboard.
            # Stash the id so the blocking page can offer resend / change email.
            request.session[UNVERIFIED_USER_KEY] = user.pk
            # Clear any signup-flow marker so a resend returns to the blocking page
            # rather than to a stale "check your email" screen.
            request.session.pop(PENDING_EMAIL_KEY, None)
            # Send a fresh link on the spot, so signing in is enough to get a usable
            # email — the visitor never has to know to press "resend". Throttled, so
            # repeated sign-in attempts can't be used to flood their inbox; when the
            # throttle blocks it, the blocking page shows a countdown instead.
            _issue_verification(user, request)
            return redirect('accounts:verify_email_required')
        login(request, user)
        request.session.pop(UNVERIFIED_USER_KEY, None)
        messages.success(request, f'Welcome back, {user.display_name}!')
        return redirect(dashboard_url_name)
    return render(request, template, {'form': form, **context})


def _unverified_user(request):
    """The user behind UNVERIFIED_USER_KEY, or None."""
    user_id = request.session.get(UNVERIFIED_USER_KEY)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id, is_verified=False).first()


def _login_url_for(user):
    return 'accounts:doctor_login' if user.is_doctor else 'accounts:patient_login'


def _dashboard_url_for(user):
    return 'doctor_dashboard' if user.is_doctor else 'patient_dashboard'


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def login_choice(request):
    """Simple landing page for choosing doctor or patient login."""
    return render(request, 'accounts/login_choice.html')


def doctor_signup(request):
    return _signup(
        request, DoctorSignUpForm, 'accounts/doctor_signup.html',
        {'role': 'doctor'},
    )


def patient_signup(request):
    return _signup(
        request, PatientSignUpForm, 'accounts/patient_signup.html',
        {'role': 'patient'},
    )


def doctor_login(request):
    return _login(request, User.DOCTOR, 'accounts/doctor_login.html',
                  'doctor_dashboard', {'role': 'doctor'})


def patient_login(request):
    return _login(request, User.PATIENT, 'accounts/patient_login.html',
                  'patient_dashboard', {'role': 'patient'})


def logout_view(request):
    """Log out, clear every browser-side trace of the session, land on the landing page.

    No `@login_required`: visiting this while already logged out should take you to
    the landing page, not bounce you to a sign-in screen.

    `logout()` already flushes the session server-side, so the email, name and role
    are gone from storage the moment it returns. The extra work here is about the
    browser, which is where those details were actually still visible:

    * the session cookie is expired explicitly, so nothing is left pointing at a
      session that no longer exists;
    * `no-store` stops the browser re-displaying a cached authenticated page — the
      Back button after logout was showing the dashboard with the user's details on
      it, because Django sets no cache headers on ordinary views.
    """
    was_authenticated = request.user.is_authenticated
    logout(request)

    if was_authenticated:
        messages.success(request, 'You have been logged out.')

    response = redirect('core:landing')
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path=settings.SESSION_COOKIE_PATH,
        domain=settings.SESSION_COOKIE_DOMAIN,
    )
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


@require_POST
@login_required
def delete_account_and_logout(request):
    """Permanently delete the current user's account, log out, and redirect.

    This is an explicit, destructive action and therefore POST-only and
    protected by `login_required` + CSRF in templates.
    """
    user = request.user
    # Capture a simple flag before deleting so we can show a message.
    had_account = bool(getattr(user, 'pk', None))
    try:
        user.delete()
    except Exception:
        # If deletion fails for some reason, still log out the session.
        pass
    logout(request)

    if had_account:
        messages.success(request, 'Your account has been permanently deleted.')

    response = redirect('core:landing')
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path=settings.SESSION_COOKIE_PATH,
        domain=settings.SESSION_COOKIE_DOMAIN,
    )
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


@login_required
def confirm_delete(request):
    """Show a confirmation form asking the user whether to delete their account.

    The form posts to `delete_account_and_logout` which performs the destructive
    action. This view is GET-only and intentionally lightweight.
    """
    return render(request, 'accounts/confirm_delete.html')

# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

def verify_email_sent(request):
    """'Check your email' page shown straight after signup (req1 §3).

    The address comes from the session rather than the URL so it is never exposed
    in a link, a browser history entry or a referrer header.
    """
    email = request.session.get(PENDING_EMAIL_KEY)
    if not email:
        # Nothing pending — most likely a direct visit or a stale bookmark.
        return redirect('accounts:login')

    user = _unverified_user(request)
    verification = EmailVerification.objects.filter(user=user).first() if user else None
    return render(request, 'accounts/verify_email_sent.html', {
        'email': email,
        # Drives the live countdown on the resend button. A link was just sent, so
        # this normally starts at the full cooldown.
        'retry_after': verification.seconds_until_resend() if verification else 0,
    })


def _complete_verification(request, user, verification):
    """Mark `user` verified, sign them in, and hand back their dashboard redirect.

    Signing in here is safe *only* because the caller has already checked the signed
    token: opening the link proves control of the mailbox, which is a stronger claim
    than a password alone. It must never be reached from a branch that skips the
    token check — see the note on the already-verified case in `verify_email`.
    """
    user.is_verified = True
    user.save(update_fields=['is_verified'])
    # Row no longer needed: the signed token self-invalidates now that is_verified
    # is part of its hash, so there is no throttle state left to keep.
    if verification:
        verification.delete()

    # Explicit backend because this user did not come from authenticate(). With a
    # single configured backend Django would infer it, but naming it keeps this
    # working if AUTHENTICATION_BACKENDS ever grows.
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    # login() cycles the session key but preserves its contents, so clear the
    # pre-verification markers explicitly.
    request.session.pop(UNVERIFIED_USER_KEY, None)
    request.session.pop(PENDING_EMAIL_KEY, None)

    messages.success(
        request,
        f'Email verified. Welcome to MedSync, {user.display_name}!',
    )
    return redirect(_dashboard_url_for(user))


def verify_email(request, uidb64, token):
    """Verify an account from a signed link, then drop the user on their dashboard.

    Every failure path renders the same friendly 'invalid or expired' page. No
    exception text, no stack trace, and no distinction between a malformed uid, an
    unknown user and a bad token — that distinction would leak which ids exist.
    """
    uid = decode_uid(uidb64)
    user = User.objects.filter(pk=uid).first() if uid else None

    if user and user.is_verified:
        # Clicking the link twice, or after verifying on another device, is a
        # success from the user's point of view rather than an error.
        #
        # Deliberately NOT signed in here. This branch is reached without checking
        # the token, and uidb64 is only base64 of the primary key — so auto-login
        # would let anyone session-hijack any verified account by walking uids.
        # They get the login page instead.
        messages.info(request, 'Your email is already verified. Please sign in.')
        return redirect(_login_url_for(user))

    if user and email_verification_token.check_token(user, token):
        verification = EmailVerification.objects.filter(user=user).first()
        if verification and verification.is_expired():
            return render(request, 'accounts/verify_email_result.html',
                          {'state': 'expired'}, status=410)
        return _complete_verification(request, user, verification)

    return render(request, 'accounts/verify_email_result.html',
                  {'state': 'invalid'}, status=400)


def verify_email_legacy(request, token):
    """Honour verification links issued before signed tokens were introduced.

    Kept so any link already sitting in an inbox still works. New links never use
    this route.
    """
    verification = EmailVerification.objects.filter(token=token).select_related('user').first()
    if not verification:
        return render(request, 'accounts/verify_email_result.html',
                      {'state': 'invalid'}, status=400)

    user = verification.user
    if user.is_verified:
        messages.info(request, 'Your email is already verified. Please sign in.')
        return redirect(_login_url_for(user))
    if verification.is_expired():
        return render(request, 'accounts/verify_email_result.html',
                      {'state': 'expired'}, status=410)

    # The unguessable UUID played the same role the signed token does now, so
    # signing in is warranted on the same grounds.
    return _complete_verification(request, user, verification)


def verify_email_required(request):
    """Blocking page for a correct password on an unverified account (req1 §6)."""
    user = _unverified_user(request)
    if not user:
        return redirect('accounts:login')

    verification = EmailVerification.objects.filter(user=user).first()
    return render(request, 'accounts/verify_email_required.html', {
        'email': user.email,
        'login_url': reverse(_login_url_for(user)),
        'retry_after': verification.seconds_until_resend() if verification else 0,
    })


def resend_verification(request):
    """Resend a verification link, rate-limited (req1 §7).

    Two callers with different disclosure rules:

    * From the blocking page, the visitor already proved the password, so specific
      feedback ('wait 45 seconds') tells them nothing they don't know.
    * Anonymously with a typed address, the response is always identical, so the
      endpoint cannot be used to test which addresses are registered.
    """
    known_user = _unverified_user(request)

    if known_user:
        if request.method == 'POST':
            outcome = _issue_verification(known_user, request)
            if outcome == 'sent':
                messages.success(request, f'Verification email sent to {known_user.email}.')
            elif outcome == 'throttled':
                messages.warning(
                    request,
                    'A verification email was sent recently. Please wait a moment '
                    'before requesting another.',
                )
            else:
                messages.error(request, SEND_FAILED)
        # Return the visitor to whichever page they came from. Derived from session
        # state rather than a submitted parameter, so there is no open-redirect path.
        if request.session.get(PENDING_EMAIL_KEY):
            return redirect('accounts:verify_email_sent')
        return redirect('accounts:verify_email_required')

    if request.method == 'POST':
        form = ResendVerificationForm(request.POST)
        if form.is_valid():
            user = User.objects.filter(
                email__iexact=form.cleaned_data['email'], is_verified=False,
            ).first()
            if user:
                _issue_verification(user, request)
            # Same message regardless of whether anything was sent.
            messages.success(request, GENERIC_EMAIL_SENT)
            return redirect('accounts:login')
    else:
        form = ResendVerificationForm()
    return render(request, 'accounts/resend_verification.html', {'form': form})


def change_email(request):
    """Correct a mistyped address before verification (req1 §6).

    Requires the unverified-session flag, which is only set after a successful
    password check — so this cannot be used to move somebody else's address.
    """
    user = _unverified_user(request)
    if not user:
        return redirect('accounts:login')

    if request.method == 'POST':
        form = ChangeEmailForm(request.POST, user=user)
        if form.is_valid():
            user.email = form.cleaned_data['email']
            user.save(update_fields=['email'])
            # Changing the address invalidates any outstanding token (the address
            # is part of the token hash), so reset the throttle and start fresh.
            EmailVerification.objects.filter(user=user).delete()
            outcome = _issue_verification(user, request, respect_throttle=False)
            if outcome == 'failed':
                messages.warning(request, SEND_FAILED)
            request.session[PENDING_EMAIL_KEY] = user.email
            return redirect('accounts:verify_email_sent')
    else:
        form = ChangeEmailForm(user=user, initial={'email': user.email})

    return render(request, 'accounts/change_email.html', {
        'form': form,
        'current_email': user.email,
        'login_url': reverse(_login_url_for(user)),
    })


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def forgot_password(request, role=None):
    """Request a reset link.

    Responds identically for registered and unregistered addresses — the previous
    'No account found with that email' told anyone which addresses exist
    (req1 §11). `role` only selects the copy shown on the page.
    """
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            user = User.objects.filter(email__iexact=form.cleaned_data['email']).first()
            if user:
                reset_token = PasswordResetToken.objects.create(user=user)
                send_password_reset_email(user, request, reset_token)
            messages.success(request, GENERIC_RESET_SENT)
            return redirect('accounts:login')
    else:
        form = ForgotPasswordForm()

    return render(request, 'accounts/forgot_password.html', {'form': form, 'role': role})


def reset_password(request, token):
    reset_token = get_object_or_404(PasswordResetToken, token=token, used=False)

    if reset_token.is_expired():
        messages.error(request, 'That reset link has expired. Please request a new one.')
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            user = reset_token.user
            user.set_password(form.cleaned_data['password'])
            user.save()
            reset_token.used = True
            reset_token.save(update_fields=['used'])
            messages.success(request, 'Password reset successfully! You can now log in.')
            return redirect(_login_url_for(user))
    else:
        form = ResetPasswordForm()

    return render(request, 'accounts/reset_password.html', {'form': form, 'token': token})


# ---------------------------------------------------------------------------
# Profile & settings
# ---------------------------------------------------------------------------

@login_required
def profile_view(request):
    """View and edit profile for both doctors and patients."""
    user = request.user

    if user.is_doctor:
        profile = user.doctor_profile
        if request.method == 'POST':
            form = DoctorProfileForm(request.POST, request.FILES, instance=profile, user=user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('doctor_profile')
        else:
            form = DoctorProfileForm(instance=profile, user=user)
        return render(request, 'accounts/doctor_profile.html', {'form': form, 'profile': profile})
    else:
        profile = user.patient_profile
        if request.method == 'POST':
            form = PatientProfileForm(request.POST, request.FILES, instance=profile, user=user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('patient_profile')
        else:
            form = PatientProfileForm(instance=profile, user=user)
        return render(request, 'accounts/patient_profile.html', {'form': form, 'profile': profile})


@login_required
def settings_view(request):
    """Settings page for both doctors and patients."""
    user = request.user

    if request.method == 'POST':
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            if user.check_password(form.cleaned_data['current_password']):
                user.set_password(form.cleaned_data['new_password'])
                user.save()
                messages.success(request, 'Password changed successfully!')
                return redirect('accounts:logout')
            else:
                form.add_error('current_password', 'Current password is incorrect.')
    else:
        form = ChangePasswordForm()

    template = 'accounts/doctor_settings.html' if user.is_doctor else 'accounts/patient_settings.html'
    return render(request, template, {'form': form})

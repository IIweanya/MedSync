"""Tests for appointment notifications and country-based booking.

Covers the two rules that span the appointments app:

* every appointment change emails *both* parties, not just the counterparty
* a patient may only book a doctor in their own country, enforced server-side and
  not merely hidden from the listing
"""

from datetime import time, timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import DoctorProfile, PatientProfile, User
from availability.models import WeeklyAvailability

from .models import Appointment

PASSWORD = 'Str0ng-Tulip-9142'


def make_doctor(email, country='NG', name='Ada Doctor'):
    user = User.objects.create_user(email=email, full_name=name, role=User.DOCTOR,
                                    password=PASSWORD, is_verified=True)
    user.country = country
    user.save(update_fields=['country'])
    DoctorProfile.objects.create(user=user, specialty='general', license_id='MD-1',
                                 appointment_duration=30, buffer_time=10)
    return user


def make_patient(email, country='NG', name='Bo Patient'):
    user = User.objects.create_user(email=email, full_name=name, role=User.PATIENT,
                                    password=PASSWORD, is_verified=True)
    user.country = country
    user.save(update_fields=['country'])
    PatientProfile.objects.create(user=user)
    return user


def make_appointment(doctor, patient, **overrides):
    fields = {
        'doctor': doctor,
        'patient': patient,
        'date': timezone.now().date() + timedelta(days=3),
        'start_time': time(10, 0),
        'end_time': time(10, 30),
        'appointment_type': Appointment.CONSULTATION,
        'status': Appointment.UPCOMING,
    }
    fields.update(overrides)
    return Appointment.objects.create(**fields)


def recipients():
    """Flat list of every address the outbox has been sent to."""
    return [addr for message in mail.outbox for addr in message.to]


class BookingNotificationTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor('doc@example.com')
        self.patient = make_patient('pat@example.com')
        self.client.force_login(self.patient)
        # A working weekday slot so the booking view has something to accept.
        target = timezone.now().date() + timedelta(days=3)
        WeeklyAvailability.objects.create(
            doctor=self.doctor, day_of_week=target.weekday(),
            start_time=time(9, 0), end_time=time(17, 0), is_active=True,
        )
        self.target_date = target

    def book(self):
        return self.client.post(
            reverse('book_appointment', kwargs={'doctor_id': self.doctor.pk}),
            {
                'appointment_type': Appointment.CONSULTATION,
                'date': self.target_date.isoformat(),
                'start_time': '10:00',
                'notes': 'Occasional headaches.',
            },
        )

    def test_booking_emails_both_parties(self):
        self.book()
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertCountEqual(recipients(), ['doc@example.com', 'pat@example.com'])

    def test_booking_email_omits_free_text_notes(self):
        """Notes can carry clinical detail, and email is a less private channel than
        the app."""
        self.book()
        for message in mail.outbox:
            self.assertNotIn('Occasional headaches', message.body)
            self.assertNotIn('Occasional headaches', message.alternatives[0][0])

    def test_booking_email_carries_the_appointment_details(self):
        self.book()
        body = mail.outbox[0].body
        self.assertIn('Consultation', body)
        self.assertIn('10:00', body)
        self.assertIn(self.doctor.display_name, body)

    def test_cancelling_emails_both_parties(self):
        appt = make_appointment(self.doctor, self.patient)
        mail.outbox.clear()
        self.client.post(reverse('patient_cancel', kwargs={'pk': appt.pk}),
                         {'reason': 'Away that week.'})
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.CANCELLED)
        self.assertCountEqual(recipients(), ['doc@example.com', 'pat@example.com'])
        self.assertIn('Away that week.', mail.outbox[0].body)

    def test_rescheduling_emails_both_parties(self):
        appt = make_appointment(self.doctor, self.patient)
        mail.outbox.clear()
        self.client.post(reverse('patient_reschedule', kwargs={'pk': appt.pk}), {
            'date': (self.target_date + timedelta(days=1)).isoformat(),
            'start_time': '11:00',
            'reason': 'Clash with work.',
        })
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.RESCHEDULED)
        self.assertCountEqual(recipients(), ['doc@example.com', 'pat@example.com'])

    def test_doctor_side_changes_email_both_parties(self):
        appt = make_appointment(self.doctor, self.patient)
        self.client.force_login(self.doctor)

        mail.outbox.clear()
        self.client.post(reverse('doctor_cancel', kwargs={'pk': appt.pk}),
                         {'reason': 'Clinic closed.'})
        self.assertCountEqual(recipients(), ['doc@example.com', 'pat@example.com'])

    def test_completion_emails_both_parties(self):
        appt = make_appointment(self.doctor, self.patient)
        self.client.force_login(self.doctor)
        mail.outbox.clear()
        self.client.post(reverse('doctor_complete', kwargs={'pk': appt.pk}),
                         {'doctor_notes': 'Prescribed rest.'})
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.COMPLETED)
        self.assertCountEqual(recipients(), ['doc@example.com', 'pat@example.com'])
        # Clinical notes stay in the app.
        for message in mail.outbox:
            self.assertNotIn('Prescribed rest', message.body)

    def test_appointment_email_has_an_html_alternative(self):
        self.book()
        message = mail.outbox[0]
        self.assertEqual(len(message.alternatives), 1)
        self.assertEqual(message.alternatives[0][1], 'text/html')


class CountryBookingRestrictionTests(TestCase):
    def setUp(self):
        self.local_doctor = make_doctor('local@example.com', country='NG',
                                        name='Local Doctor')
        self.foreign_doctor = make_doctor('foreign@example.com', country='US',
                                          name='Foreign Doctor')
        self.patient = make_patient('pat@example.com', country='NG')
        self.client.force_login(self.patient)

    def test_only_same_country_doctors_are_listed(self):
        response = self.client.get(reverse('find_doctor'))
        listed = list(response.context['doctors'])
        self.assertIn(self.local_doctor, listed)
        self.assertNotIn(self.foreign_doctor, listed)

    def test_booking_a_foreign_doctor_is_refused(self):
        """The listing hides them, but /patient/book/<id>/ is guessable by id."""
        response = self.client.get(
            reverse('book_appointment', kwargs={'doctor_id': self.foreign_doctor.pk}))
        self.assertRedirects(response, reverse('find_doctor'))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_posting_a_booking_to_a_foreign_doctor_creates_nothing(self):
        self.client.post(
            reverse('book_appointment', kwargs={'doctor_id': self.foreign_doctor.pk}),
            {
                'appointment_type': Appointment.CONSULTATION,
                'date': (timezone.now().date() + timedelta(days=3)).isoformat(),
                'start_time': '10:00',
            },
        )
        self.assertEqual(Appointment.objects.count(), 0)

    def test_booking_a_same_country_doctor_is_allowed(self):
        response = self.client.get(
            reverse('book_appointment', kwargs={'doctor_id': self.local_doctor.pk}))
        self.assertEqual(response.status_code, 200)

    def test_patient_without_a_country_sees_no_doctors(self):
        """Blank country excludes rather than matches everything — we can't confirm
        two people share a location if we don't know one of them."""
        self.patient.country = ''
        self.patient.save(update_fields=['country'])
        response = self.client.get(reverse('find_doctor'))
        self.assertEqual(list(response.context['doctors']), [])
        # And the page says how to fix it rather than just showing an empty list.
        self.assertContains(response, 'Add your country')

    def test_patient_without_a_country_is_sent_to_their_profile(self):
        self.patient.country = ''
        self.patient.save(update_fields=['country'])
        response = self.client.get(
            reverse('book_appointment', kwargs={'doctor_id': self.local_doctor.pk}))
        self.assertRedirects(response, reverse('accounts:profile_view'))

    def test_doctor_without_a_country_is_not_bookable(self):
        self.local_doctor.country = ''
        self.local_doctor.save(update_fields=['country'])
        response = self.client.get(reverse('find_doctor'))
        self.assertEqual(list(response.context['doctors']), [])

    def test_doctor_scheduling_only_offers_same_country_patients(self):
        foreign_patient = make_patient('foreign-pat@example.com', country='US',
                                       name='Foreign Patient')
        self.client.force_login(self.local_doctor)
        response = self.client.get(reverse('doctor_schedule_appointment'))
        offered = list(response.context['patients'])
        self.assertIn(self.patient, offered)
        self.assertNotIn(foreign_patient, offered)

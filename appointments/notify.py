"""Appointment notifications — in-app record plus email, for both parties.

Every appointment state change goes through one of the `notify_*` functions here
rather than calling `create_notification` directly. Two reasons: the doctor and the
patient must both hear about a change regardless of which of them made it (before
this, a patient cancelling told the doctor but never confirmed it back to the
patient), and the in-app notification and the email can't drift apart if one call
produces both.

Deliberately excluded from emails: `notes` and `doctor_notes`. Those are free-text
fields that can hold clinical detail, and email is a less private channel than the
app. Cancellation and reschedule reasons *are* included — they're operationally
necessary, and both parties can already read them in the app.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from notifications.models import Notification
from notifications.utils import create_notification

logger = logging.getLogger(__name__)


def _appointment_email(recipient, request, subject, heading, intro, appointment,
                       detail_url_name, reason=None, reason_label=None):
    """Send one appointment email. Never raises — a mail failure must not roll back
    an appointment that was already saved."""
    path = reverse(detail_url_name, kwargs={'pk': appointment.pk})
    context = {
        'recipient': recipient,
        'heading': heading,
        'intro': intro,
        'appointment': appointment,
        'reason': reason,
        'reason_label': reason_label,
        'support_email': getattr(settings, 'SUPPORT_EMAIL', ''),
        # Absolute, and inherits the scheme from the request, so it is https behind
        # a TLS-terminating proxy without hard-coding a host anywhere.
        'detail_url': request.build_absolute_uri(path),
    }
    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string('emails/appointment_update.txt', context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient.email],
        )
        message.attach_alternative(
            render_to_string('emails/appointment_update.html', context), 'text/html')
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Failed to email %s about appointment %s',
                         recipient.email, appointment.pk)
        return False


def _when(appointment):
    return f'{appointment.date:%d %b %Y} at {appointment.start_time:%H:%M}'


def _notify_pair(appointment, request, notification_type, doctor_title, doctor_message,
                 patient_title, patient_message, subject, doctor_intro,
                 patient_intro, reason=None, reason_label=None):
    """In-app notification + email for the doctor and the patient."""
    doctor, patient = appointment.doctor, appointment.patient

    create_notification(user=doctor, notification_type=notification_type,
                        title=doctor_title, message=doctor_message,
                        appointment=appointment)
    create_notification(user=patient, notification_type=notification_type,
                        title=patient_title, message=patient_message,
                        appointment=appointment)

    _appointment_email(doctor, request, subject, doctor_title, doctor_intro,
                       appointment, 'doctor_appointment_detail', reason, reason_label)
    _appointment_email(patient, request, subject, patient_title, patient_intro,
                       appointment, 'patient_appointment_detail', reason, reason_label)


def notify_booked(appointment, request, booked_by_doctor=False):
    """A new appointment exists."""
    doctor, patient = appointment.doctor, appointment.patient
    when = _when(appointment)
    if booked_by_doctor:
        subject = f'Appointment scheduled — {when}'
        patient_intro = (
            f'{doctor.display_name} has scheduled an appointment with you. '
            'The details are below.'
        )
        doctor_intro = f'You scheduled an appointment with {patient.full_name}.'
    else:
        # Patient-initiated: this is a request for a slot, not a settled booking.
        # The doctor confirms the day and time (see notify_confirmed), so the copy
        # must not promise the requested time will be the one that happens.
        subject = f'Appointment requested — {when}'
        patient_intro = (
            f'Your appointment request with {doctor.display_name} for {when} has been '
            'received. You will get another email once the doctor confirms the day '
            'and time.'
        )
        doctor_intro = (
            f'{patient.full_name} has requested an appointment for {when}. '
            'Confirm the day and time to finalise it.'
        )

    _notify_pair(
        appointment, request,
        notification_type=Notification.NEW_APPOINTMENT,
        doctor_title='New Appointment', doctor_message=f'{patient.full_name} — {when}.',
        patient_title='Appointment Booked' if booked_by_doctor else 'Appointment Requested',
        patient_message=f'With {doctor.display_name} — {when}.',
        subject=subject, doctor_intro=doctor_intro, patient_intro=patient_intro,
    )


def notify_rescheduled(new_appointment, old_appointment, request,
                       rescheduled_by_doctor=False):
    """An appointment moved. Notifies about the *new* appointment, naming the old slot."""
    doctor, patient = new_appointment.doctor, new_appointment.patient
    was = _when(old_appointment)
    now = _when(new_appointment)
    actor = doctor.display_name if rescheduled_by_doctor else patient.full_name

    _notify_pair(
        new_appointment, request,
        notification_type=Notification.APPOINTMENT_RESCHEDULED,
        doctor_title='Appointment Rescheduled',
        doctor_message=f'{patient.full_name}: {was} → {now}.',
        patient_title='Appointment Rescheduled',
        patient_message=f'{doctor.display_name}: {was} → {now}.',
        subject=f'Appointment rescheduled — now {now}',
        doctor_intro=f'{actor} moved this appointment from {was}. It is now {now}.',
        patient_intro=f'{actor} moved this appointment from {was}. It is now {now}.',
        reason=new_appointment.reschedule_reason or None,
        reason_label='Reason for rescheduling',
    )


def notify_cancelled(appointment, request, cancelled_by_doctor=False):
    doctor, patient = appointment.doctor, appointment.patient
    when = _when(appointment)
    actor = doctor.display_name if cancelled_by_doctor else patient.full_name

    _notify_pair(
        appointment, request,
        notification_type=Notification.APPOINTMENT_CANCELLED,
        doctor_title='Appointment Cancelled',
        doctor_message=f'{patient.full_name} — {when}.',
        patient_title='Appointment Cancelled',
        patient_message=f'{doctor.display_name} — {when}.',
        subject=f'Appointment cancelled — {when}',
        doctor_intro=f'{actor} cancelled this appointment.',
        patient_intro=f'{actor} cancelled this appointment.',
        reason=appointment.cancel_reason or None,
        reason_label='Reason for cancellation',
    )


def notify_confirmed(appointment, request, requested_date=None, requested_time=None):
    """The doctor has settled the final day and time.

    A patient's booking is a *request*; the doctor sets the slot that actually
    happens. When that differs from what was asked for, the email says so explicitly
    — "you asked for X, it is now Y" — rather than just stating the new time and
    leaving the patient to notice the change themselves.
    """
    doctor, patient = appointment.doctor, appointment.patient
    now = _when(appointment)

    moved = bool(
        requested_date and requested_time
        and (requested_date != appointment.date or requested_time != appointment.start_time)
    )
    if moved:
        was = f'{requested_date:%d %b %Y} at {requested_time:%H:%M}'
        patient_intro = (
            f'{doctor.display_name} has confirmed your appointment. You requested '
            f'{was}; it has been set for {now}.'
        )
        doctor_intro = f'You confirmed {patient.full_name}, moved from {was} to {now}.'
        subject = f'Appointment confirmed — moved to {now}'
    else:
        patient_intro = (
            f'{doctor.display_name} has confirmed your appointment for {now}.'
        )
        doctor_intro = f'You confirmed {patient.full_name} for {now}.'
        subject = f'Appointment confirmed — {now}'

    _notify_pair(
        appointment, request,
        notification_type=Notification.APPOINTMENT_CONFIRMED,
        doctor_title='Appointment Confirmed',
        doctor_message=f'{patient.full_name} — {now}.',
        patient_title='Appointment Confirmed',
        patient_message=f'{doctor.display_name} — {now}.',
        subject=subject, doctor_intro=doctor_intro, patient_intro=patient_intro,
    )


def notify_completed(appointment, request):
    doctor, patient = appointment.doctor, appointment.patient
    when = _when(appointment)

    _notify_pair(
        appointment, request,
        notification_type=Notification.APPOINTMENT_COMPLETED,
        doctor_title='Appointment Completed',
        doctor_message=f'{patient.full_name} — {when}.',
        patient_title='Appointment Completed',
        patient_message=f'{doctor.display_name} — {when}.',
        subject=f'Appointment completed — {when}',
        doctor_intro=f'You marked this appointment with {patient.full_name} as completed.',
        patient_intro=(
            f'Your appointment with {doctor.display_name} has been marked as '
            'completed. Any notes from your doctor are available in the app.'
        ),
    )

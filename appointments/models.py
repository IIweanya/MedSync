from django.db import models
from django.conf import settings
from django.utils import timezone


class Appointment(models.Model):
    # Statuses
    UPCOMING = 'upcoming'
    CONFIRMED = 'confirmed'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    RESCHEDULED = 'rescheduled'
    NO_SHOW = 'no_show'

    STATUS_CHOICES = [
        (UPCOMING, 'Upcoming'),
        (CONFIRMED, 'Confirmed'),
        (COMPLETED, 'Completed'),
        (CANCELLED, 'Cancelled'),
        (RESCHEDULED, 'Rescheduled'),
        (NO_SHOW, 'No Show'),
    ]

    STATUS_COLORS = {
        UPCOMING: 'blue',
        CONFIRMED: 'green',
        COMPLETED: 'gray',
        CANCELLED: 'red',
        RESCHEDULED: 'orange',
        NO_SHOW: 'yellow',
    }

    # Appointment types
    CONSULTATION = 'consultation'
    FOLLOW_UP = 'follow_up'
    CHECKUP = 'checkup'
    VIDEO = 'video'
    IN_PERSON = 'in_person'

    TYPE_CHOICES = [
        (CONSULTATION, 'Consultation'),
        (FOLLOW_UP, 'Follow-up'),
        (CHECKUP, 'Routine Checkup'),
        (VIDEO, 'Video Consultation'),
        (IN_PERSON, 'In-person Consultation'),
    ]

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='doctor_appointments',
        limit_choices_to={'role': 'doctor'},
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='patient_appointments',
        limit_choices_to={'role': 'patient'},
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    appointment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=CONSULTATION)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=UPCOMING)
    notes = models.TextField(blank=True)
    doctor_notes = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)
    reschedule_reason = models.TextField(blank=True)
    rescheduled_from = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='rescheduled_to',
    )
    created_by = models.CharField(
        max_length=10,
        choices=[('doctor', 'Doctor'), ('patient', 'Patient')],
        default='patient',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'start_time']

    def __str__(self):
        return (
            f'{self.get_appointment_type_display()} — '
            f'{self.doctor.display_name} & {self.patient.full_name} '
            f'on {self.date} at {self.start_time}'
        )

    def get_status_color(self):
        return self.STATUS_COLORS.get(self.status, 'gray')

    def is_upcoming(self):
        now = timezone.now()
        from datetime import datetime, timezone as dt_tz
        appt_dt = datetime.combine(self.date, self.start_time).replace(tzinfo=dt_tz.utc)
        return appt_dt > now

    def duration_display(self):
        from datetime import datetime
        dt_start = datetime.combine(self.date, self.start_time)
        dt_end = datetime.combine(self.date, self.end_time)
        diff = dt_end - dt_start
        minutes = int(diff.total_seconds() / 60)
        return f'{minutes} min'

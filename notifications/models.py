from django.db import models
from django.conf import settings


class Notification(models.Model):
    APPOINTMENT_CONFIRMED = 'appointment_confirmed'
    APPOINTMENT_CANCELLED = 'appointment_cancelled'
    APPOINTMENT_RESCHEDULED = 'appointment_rescheduled'
    APPOINTMENT_REMINDER = 'appointment_reminder'
    NEW_APPOINTMENT = 'new_appointment'
    AVAILABILITY_CHANGED = 'availability_changed'
    APPOINTMENT_COMPLETED = 'appointment_completed'
    APPOINTMENT_NO_SHOW = 'appointment_no_show'

    TYPE_CHOICES = [
        (APPOINTMENT_CONFIRMED, 'Appointment Confirmed'),
        (APPOINTMENT_CANCELLED, 'Appointment Cancelled'),
        (APPOINTMENT_RESCHEDULED, 'Appointment Rescheduled'),
        (APPOINTMENT_REMINDER, 'Appointment Reminder'),
        (NEW_APPOINTMENT, 'New Appointment'),
        (AVAILABILITY_CHANGED, 'Availability Changed'),
        (APPOINTMENT_COMPLETED, 'Appointment Completed'),
        (APPOINTMENT_NO_SHOW, 'No Show'),
    ]

    TYPE_ICONS = {
        APPOINTMENT_CONFIRMED: 'check-circle',
        APPOINTMENT_CANCELLED: 'x-circle',
        APPOINTMENT_RESCHEDULED: 'refresh-cw',
        APPOINTMENT_REMINDER: 'bell',
        NEW_APPOINTMENT: 'calendar-plus',
        AVAILABILITY_CHANGED: 'clock',
        APPOINTMENT_COMPLETED: 'check-square',
        APPOINTMENT_NO_SHOW: 'user-x',
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    appointment = models.ForeignKey(
        'appointments.Appointment',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='notifications',
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_notification_type_display()}] → {self.user.email}'

    def get_icon(self):
        return self.TYPE_ICONS.get(self.notification_type, 'bell')

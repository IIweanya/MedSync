from django.db import models
from django.conf import settings


class WeeklyAvailability(models.Model):
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='weekly_availability',
        limit_choices_to={'role': 'doctor'},
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['doctor', 'day_of_week']
        ordering = ['day_of_week', 'start_time']

    def __str__(self):
        return f'{self.get_day_of_week_display()}: {self.start_time} – {self.end_time}'


class AvailabilityException(models.Model):
    """Full-day or partial-day blocks (holidays, personal time off)."""

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='availability_exceptions',
        limit_choices_to={'role': 'doctor'},
    )
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)  # null = full day block
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['date', 'start_time']

    def __str__(self):
        if self.start_time:
            return f'{self.doctor.display_name} blocked on {self.date} {self.start_time}–{self.end_time}'
        return f'{self.doctor.display_name} fully blocked on {self.date}'

    @property
    def is_full_day(self):
        return self.start_time is None

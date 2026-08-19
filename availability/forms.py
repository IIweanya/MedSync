from django import forms
from .models import AvailabilityException


class AvailabilityExceptionForm(forms.ModelForm):
    class Meta:
        model = AvailabilityException
        fields = ['date', 'start_time', 'end_time', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if start and end and end <= start:
            self.add_error('end_time', 'End time must be after start time.')
        return cleaned


# Alias kept for import compatibility
WeeklyAvailabilityFormSet = None

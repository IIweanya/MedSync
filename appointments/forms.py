from django import forms
from django.utils import timezone
from .models import Appointment


class AppointmentForm(forms.ModelForm):
    """Used by doctors to create/schedule an appointment."""

    class Meta:
        model = Appointment
        fields = ['patient', 'date', 'start_time', 'end_time', 'appointment_type', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if doctor:
            # Same-country patients only. Narrowing the queryset — not just the
            # rendered dropdown — is what actually stops a hand-crafted POST from
            # scheduling a patient who could never book this doctor themselves.
            from .scoping import patients_bookable_by
            self.fields['patient'].queryset = patients_bookable_by(doctor).order_by('full_name')
            self.fields['patient'].label_from_instance = lambda obj: obj.full_name

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get('date')
        start_time = cleaned.get('start_time')
        end_time = cleaned.get('end_time')

        if date and date < timezone.now().date():
            self.add_error('date', 'Cannot schedule an appointment in the past.')

        if start_time and end_time and end_time <= start_time:
            self.add_error('end_time', 'End time must be after start time.')

        return cleaned


class PatientBookingForm(forms.ModelForm):
    """Used by patients to book appointments (step-by-step)."""

    class Meta:
        model = Appointment
        fields = ['appointment_type', 'date', 'start_time', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
        }


class ConfirmAppointmentForm(forms.Form):
    """Doctor confirms an appointment, setting the day and time that will happen.

    Separate from RescheduleForm because confirming is not a reschedule: it settles a
    request for the first time and keeps one appointment row, where a reschedule
    supersedes a confirmed slot with a new row.
    """

    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))

    def clean_date(self):
        date = self.cleaned_data['date']
        if date < timezone.now().date():
            raise forms.ValidationError('Cannot confirm an appointment in the past.')
        return date


class RescheduleForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Reason for rescheduling',
    )

    def clean_date(self):
        date = self.cleaned_data['date']
        if date < timezone.now().date():
            raise forms.ValidationError('Cannot reschedule to a past date.')
        return date


class CancelForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        label='Reason for cancellation',
    )

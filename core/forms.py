from django import forms


class ContactForm(forms.Form):
    """Public contact form.

    Deliberately minimal — a contact page whose form silently discarded the message
    would be worse than no form at all, so this is wired to actually deliver
    (see core/views.py) using the project's configured email backend.
    """

    SUBJECT_CHOICES = [
        ('general', 'General enquiry'),
        ('doctor', 'Question about doctor accounts'),
        ('patient', 'Question about patient accounts'),
        ('technical', 'Technical problem'),
        ('privacy', 'Privacy or data request'),
    ]

    name = forms.CharField(max_length=120)
    email = forms.EmailField(error_messages={'invalid': 'Please enter a valid email address.'})
    subject = forms.ChoiceField(choices=SUBJECT_CHOICES)
    message = forms.CharField(
        widget=forms.Textarea,
        max_length=4000,
        error_messages={'required': 'Please tell us how we can help.'},
    )

    def clean_message(self):
        message = self.cleaned_data['message'].strip()
        if len(message) < 10:
            raise forms.ValidationError('Please add a little more detail (at least 10 characters).')
        return message

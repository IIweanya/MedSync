from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .countries import (
    COUNTRY_CHOICES, DEFAULT_COUNTRY, DIAL_BY_ISO,
    MAX_NATIONAL_DIGITS, MIN_NATIONAL_DIGITS,
)
from .models import User, DoctorProfile, PatientProfile


def country_code_field():
    """Build the country <select> field.

    A factory rather than a shared module-level instance: form fields are mutable
    and get bound per form, so two forms must never share one object. And it is
    declared on each concrete form rather than on PhoneFieldMixin because Django's
    form metaclass only harvests `declared_fields` from form base classes — a
    `Field` sitting on a plain mixin is silently ignored.
    """
    return forms.ChoiceField(
        choices=COUNTRY_CHOICES,
        initial=DEFAULT_COUNTRY,
        label='Country',
        error_messages={'invalid_choice': 'Please choose a valid country.'},
    )


class PhoneFieldMixin:
    """Validation and combining for the country-code + national-number pair.

    The two inputs are one logical value but two form fields, which is what makes
    the pair survive a failed submit: `phone` holds only the national digits, and
    the dial code is applied once, server-side, in `get_e164`. The previous
    client-side approach rewrote the visible input to the full +234... form on
    submit, so a validation error re-rendered an already-prefixed value and the
    next submit prefixed it again.

    Concrete forms must declare `country_code = country_code_field()` themselves.
    """

    def clean_phone(self):
        """Normalise to bare digits and range-check the national part."""
        raw = (self.cleaned_data.get('phone') or '').strip()
        if not raw:
            return ''
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if not digits:
            raise ValidationError('Please enter a valid phone number.')
        if len(digits) < MIN_NATIONAL_DIGITS:
            raise ValidationError('That phone number looks too short.')
        if len(digits) > MAX_NATIONAL_DIGITS:
            raise ValidationError('That phone number looks too long.')
        return digits

    def get_e164(self):
        """Dial code + national digits, e.g. '+2348012345678'. '' when no number."""
        digits = self.cleaned_data.get('phone') or ''
        if not digits:
            return ''
        dial = DIAL_BY_ISO.get(self.cleaned_data.get('country_code'), '')
        return f'{dial}{digits}'

    def apply_phone_and_country(self, user):
        """Copy both halves of the phone field onto `user`.

        The country is stored in its own column, not re-derived from the phone
        number later: a saved '+1…' could be either the US or Canada, and the
        country decides which doctors a patient may book. It is also set even when
        the phone number is left blank, so the booking filter still works.
        """
        user.phone = self.get_e164()
        user.country = self.cleaned_data.get('country_code', '')


class EmailUniquenessMixin:
    """Shared duplicate-email check for the signup forms (req2 §2).

    Signup is the one place where an explicit 'already registered' message is
    correct: req2 asks for it by name, and a registration form cannot be usable
    without telling the user why their submission failed. The anonymous
    resend/forgot-password endpoints stay deliberately generic instead — see
    accounts/views.py.
    """

    DUPLICATE_EMAIL_MESSAGE = 'An account with this email already exists.'

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError(self.DUPLICATE_EMAIL_MESSAGE)
        return email


class DoctorSignUpForm(PhoneFieldMixin, EmailUniquenessMixin, forms.ModelForm):
    country_code = country_code_field()
    specialty = forms.ChoiceField(choices=DoctorProfile.SPECIALTY_CHOICES)
    license_id = forms.CharField(max_length=100)
    password = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')
    agree_terms = forms.BooleanField(
        error_messages={'required': 'Please accept the Terms of Service to continue.'},
    )

    class Meta:
        model = User
        fields = ['full_name', 'email', 'phone']

    def clean_password(self):
        pwd = self.cleaned_data.get('password')
        if pwd:
            validate_password(pwd)
        return pwd

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password') != cleaned.get('password2'):
            self.add_error('password2', 'Passwords do not match.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.DOCTOR
        self.apply_phone_and_country(user)
        user.set_password(self.cleaned_data['password'])
        # New accounts start unverified; only the verification view flips this.
        user.is_verified = False
        if commit:
            user.save()
            DoctorProfile.objects.create(
                user=user,
                specialty=self.cleaned_data['specialty'],
                license_id=self.cleaned_data['license_id'],
            )
        return user


class PatientSignUpForm(PhoneFieldMixin, EmailUniquenessMixin, forms.ModelForm):
    country_code = country_code_field()
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
    )
    password = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')
    agree_terms = forms.BooleanField(
        error_messages={'required': 'Please accept the Terms of Service to continue.'},
    )

    class Meta:
        model = User
        fields = ['full_name', 'email', 'phone']

    def clean_password(self):
        pwd = self.cleaned_data.get('password')
        if pwd:
            validate_password(pwd)
        return pwd

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password') != cleaned.get('password2'):
            self.add_error('password2', 'Passwords do not match.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.PATIENT
        self.apply_phone_and_country(user)
        user.set_password(self.cleaned_data['password'])
        user.is_verified = False
        if commit:
            user.save()
            PatientProfile.objects.create(
                user=user,
                date_of_birth=self.cleaned_data.get('date_of_birth'),
            )
        return user


class LoginForm(forms.Form):
    """Shared login form for both roles.

    Authentication lives here rather than in the view so a bad credential renders
    as a normal non-field form error in the same styling as every other error
    (req1 §9), instead of a floating toast.

    Every failure mode — unknown address, wrong password, right password but the
    other role's account — produces one identical message. Distinguishing them
    would let anyone probe which addresses are registered, and as which role
    (req1 §6).
    """

    INVALID_CREDENTIALS = 'Invalid email or password. Please try again.'
    INACTIVE_ACCOUNT = 'This account has been deactivated. Please contact support.'

    email = forms.EmailField(error_messages={'invalid': 'Please enter a valid email address.'})
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, request=None, role=None, **kwargs):
        self.request = request
        self.role = role
        #: Set on success. May be an unverified user — the view decides what to do
        #: about that, because an unverified login is not a credential failure.
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        password = cleaned.get('password')
        if not (email and password):
            return cleaned

        user = authenticate(self.request, username=email, password=password)
        if user is None or (self.role and user.role != self.role):
            raise ValidationError(self.INVALID_CREDENTIALS, code='invalid_login')
        if not user.is_active:
            raise ValidationError(self.INACTIVE_ACCOUNT, code='inactive')

        self.user = user
        return cleaned


class ResendVerificationForm(forms.Form):
    """Email-only form for the anonymous resend endpoint.

    Intentionally has no existence check — the view responds identically whether
    or not the address is registered (req1 §7).
    """

    email = forms.EmailField(error_messages={'invalid': 'Please enter a valid email address.'})


class ChangeEmailForm(forms.Form):
    """Lets a user correct a typo'd address before their account is verified."""

    email = forms.EmailField(
        label='New Email Address',
        error_messages={'invalid': 'Please enter a valid email address.'},
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email']
        if email.lower() == self.user.email.lower():
            raise ValidationError('That is already the address on your account.')
        # `exclude(pk=...)` so re-entering their own address in different casing
        # is treated by the check above, not reported as someone else's account.
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError('An account with this email already exists.')
        return email


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(error_messages={'invalid': 'Please enter a valid email address.'})


class ResetPasswordForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, label='New Password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')

    def clean_password(self):
        pwd = self.cleaned_data.get('password')
        if pwd:
            validate_password(pwd)
        return pwd

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password') != cleaned.get('password2'):
            self.add_error('password2', 'Passwords do not match.')
        return cleaned


class PhotoValidationMixin:
    """Restricts profile photos to JPEG and PNG.

    Two layers, because they catch different things:

    * the extension check gives the exact message the user expects when they pick a
      `.gif` or `.webp`;
    * `Pillow` verification via Django's ImageField already rejects files that
      aren't images at all, including a `.exe` renamed to `.png`.

    The `accept` attribute on the input is a convenience, not a control — a file
    picker can be overridden, so this has to hold server-side.
    """

    ALLOWED_PHOTO_EXTENSIONS = ('.jpg', '.jpeg', '.png')
    PHOTO_FORMAT_MESSAGE = (
        'The profile image has to be in .jpg, .jpeg or .png format.'
    )
    #: Generous for a profile picture, but bounded — an unbounded upload is a cheap
    #: way to fill the disk.
    MAX_PHOTO_BYTES = 5 * 1024 * 1024

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if not photo:
            return photo

        # An existing stored photo re-submitted unchanged has no new name to check.
        name = getattr(photo, 'name', '') or ''
        if name and not name.lower().endswith(self.ALLOWED_PHOTO_EXTENSIONS):
            raise ValidationError(self.PHOTO_FORMAT_MESSAGE)

        size = getattr(photo, 'size', 0) or 0
        if size > self.MAX_PHOTO_BYTES:
            raise ValidationError('That image is larger than 5 MB. Please choose a smaller file.')

        return photo


class CountryProfileMixin:
    """Adds an editable country to a profile form.

    Needed because the country gates who a patient can book with: accounts created
    before the field existed have none, and would otherwise be permanently unable to
    book (or be booked with) and have no way to fix it.
    """

    def init_country(self):
        self.fields['country'] = forms.ChoiceField(
            choices=[('', 'Select your country')] + list(COUNTRY_CHOICES),
            required=False,
            label='Country',
            help_text='Patients can only book with doctors in the same country.',
        )
        if self.user:
            self.fields['country'].initial = self.user.country

    def apply_country(self, user):
        user.country = self.cleaned_data.get('country', '')


class DoctorProfileForm(PhotoValidationMixin, CountryProfileMixin, forms.ModelForm):
    full_name = forms.CharField(max_length=255)
    phone = forms.CharField(max_length=20, required=False)

    class Meta:
        model = DoctorProfile
        fields = ['specialty', 'license_id', 'bio', 'photo', 'location',
                  'appointment_duration', 'buffer_time', 'timezone', 'consultation_types']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.init_country()
        if self.user:
            self.fields['full_name'].initial = self.user.full_name
            self.fields['phone'].initial = self.user.phone

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.full_name = self.cleaned_data['full_name']
            self.user.phone = self.cleaned_data.get('phone', '')
            self.apply_country(self.user)
            self.user.save()
        if commit:
            profile.save()
        return profile


class PatientProfileForm(PhotoValidationMixin, CountryProfileMixin, forms.ModelForm):
    full_name = forms.CharField(max_length=255)
    phone = forms.CharField(max_length=20, required=False)

    class Meta:
        model = PatientProfile
        fields = ['date_of_birth', 'photo', 'address',
                  'emergency_contact_name', 'emergency_contact_phone']
        widgets = {'date_of_birth': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.init_country()
        if self.user:
            self.fields['full_name'].initial = self.user.full_name
            self.fields['phone'].initial = self.user.phone

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.full_name = self.cleaned_data['full_name']
            self.user.phone = self.cleaned_data.get('phone', '')
            self.apply_country(self.user)
            self.user.save()
        if commit:
            profile.save()
        return profile


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput)
    new_password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean_new_password(self):
        pwd = self.cleaned_data.get('new_password')
        if pwd:
            validate_password(pwd)
        return pwd

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('new_password') != cleaned.get('confirm_password'):
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned

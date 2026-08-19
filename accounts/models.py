import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, full_name, role, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_verified', True)
        return self.create_user(email, full_name, 'doctor', password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    DOCTOR = 'doctor'
    PATIENT = 'patient'
    ROLE_CHOICES = [(DOCTOR, 'Doctor'), (PATIENT, 'Patient')]

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    # ISO 3166-1 alpha-2, captured from the signup country selector. Stored
    # separately from `phone` because it drives who a patient can book with, and a
    # dial code parsed back out of a phone number is ambiguous (+1 is both the US
    # and Canada). Required at signup but blank-able, so pre-existing accounts stay
    # valid until their owner sets one from their profile page.
    country = models.CharField(max_length=2, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def is_doctor(self):
        return self.role == self.DOCTOR

    @property
    def is_patient(self):
        return self.role == self.PATIENT

    @property
    def display_name(self):
        if self.role == self.DOCTOR:
            return f'Dr. {self.full_name}'
        return self.full_name

    @property
    def country_name(self):
        """Human-readable country, or '' when unset."""
        from .countries import NAME_BY_ISO
        return NAME_BY_ISO.get(self.country, '')

    @property
    def country_flag(self):
        from .countries import flag
        return flag(self.country) if self.country else ''

    @property
    def country_label(self):
        """Flag + name, for display. Empty string when no country is set."""
        if not self.country:
            return ''
        return f'{self.country_flag} {self.country_name}'.strip()

    def get_photo_url(self):
        if self.role == self.DOCTOR:
            try:
                if self.doctor_profile.photo:
                    return self.doctor_profile.photo.url
            except DoctorProfile.DoesNotExist:
                pass
        else:
            try:
                if self.patient_profile.photo:
                    return self.patient_profile.photo.url
            except PatientProfile.DoesNotExist:
                pass
        return None


class DoctorProfile(models.Model):
    SPECIALTY_CHOICES = [
        ('general', 'General Practice'),
        ('cardiology', 'Cardiology'),
        ('dermatology', 'Dermatology'),
        ('neurology', 'Neurology'),
        ('orthopedics', 'Orthopedics'),
        ('pediatrics', 'Pediatrics'),
        ('psychiatry', 'Psychiatry'),
        ('radiology', 'Radiology'),
        ('surgery', 'Surgery'),
        ('gynecology', 'Gynecology & Obstetrics'),
        ('ophthalmology', 'Ophthalmology'),
        ('ent', 'ENT (Ear, Nose & Throat)'),
        ('oncology', 'Oncology'),
        ('urology', 'Urology'),
        ('endocrinology', 'Endocrinology'),
        ('other', 'Other'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='doctor_profile')
    specialty = models.CharField(max_length=100, choices=SPECIALTY_CHOICES)
    license_id = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to='doctors/photos/', blank=True, null=True)
    location = models.CharField(max_length=255, blank=True)
    appointment_duration = models.PositiveIntegerField(default=30, help_text='Duration in minutes')
    buffer_time = models.PositiveIntegerField(default=10, help_text='Buffer between appointments in minutes')
    timezone = models.CharField(max_length=50, default='UTC')
    consultation_types = models.CharField(max_length=500, blank=True,
                                          help_text='Comma-separated list of consultation types offered')

    def __str__(self):
        return f'Dr. {self.user.full_name} — {self.get_specialty_display()}'

    def get_consultation_types_list(self):
        if self.consultation_types:
            return [t.strip() for t in self.consultation_types.split(',')]
        return []


class PatientProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='patient_profile')
    date_of_birth = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to='patients/photos/', blank=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.user.full_name

    def age(self):
        if self.date_of_birth:
            from datetime import date
            today = date.today()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None


class EmailVerification(models.Model):
    """Per-user verification state and resend throttle.

    The token in the verification *link* is a signed HMAC (see accounts/tokens.py)
    and is deliberately not stored here — there is nothing to leak from the
    database. This row exists for the two things a stateless token cannot express:
    when the current link was issued (expiry window) and how often the user has
    asked us to send another one (rate limiting, req1 §7).
    """

    #: Verification links stop working this long after they were last sent.
    EXPIRY_SECONDS = 24 * 60 * 60
    #: Minimum gap between two resend requests for the same account.
    RESEND_COOLDOWN_SECONDS = 60
    #: Maximum resends allowed inside one RESEND_WINDOW.
    RESEND_MAX = 3
    RESEND_WINDOW_SECONDS = 60 * 60

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    # Legacy column from the pre-signed-token scheme. Kept so verification links
    # already sent to the old /accounts/<role>/verify/<uuid>/ route still resolve.
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    resend_count = models.PositiveIntegerField(default=0)
    resend_window_started_at = models.DateTimeField(null=True, blank=True)

    def is_expired(self):
        issued = self.last_sent_at or self.created_at
        return (timezone.now() - issued).total_seconds() > self.EXPIRY_SECONDS

    def seconds_until_resend(self):
        """Seconds the user must wait before another resend, 0 if they may send now."""
        if not self.last_sent_at:
            return 0
        elapsed = (timezone.now() - self.last_sent_at).total_seconds()
        return max(0, int(self.RESEND_COOLDOWN_SECONDS - elapsed))

    def can_resend(self):
        """(allowed, reason) — reason is a user-safe string when not allowed."""
        if self.seconds_until_resend() > 0:
            return False, 'cooldown'
        if self._window_is_open() and self.resend_count >= self.RESEND_MAX:
            return False, 'quota'
        return True, ''

    def _window_is_open(self):
        if not self.resend_window_started_at:
            return False
        age = (timezone.now() - self.resend_window_started_at).total_seconds()
        return age < self.RESEND_WINDOW_SECONDS

    def mark_sent(self):
        """Record that a verification email just went out, refreshing the expiry."""
        now = timezone.now()
        if not self._window_is_open():
            self.resend_window_started_at = now
            self.resend_count = 0
        self.resend_count += 1
        self.last_sent_at = now
        self.save(update_fields=['resend_count', 'resend_window_started_at', 'last_sent_at'])

    def __str__(self):
        return f'Verification for {self.user.email}'


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    def is_expired(self):
        return (timezone.now() - self.created_at).total_seconds() > 3600  # 1 hour

    def __str__(self):
        return f'Password reset for {self.user.email}'

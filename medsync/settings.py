import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Kept as a fallback so an existing checkout keeps working without a .env, but set
# SECRET_KEY (and DEBUG=False) in the environment before deploying anywhere real.
SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-change-this-in-production-medsync-secret-key',
)

DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Local apps
    'accounts',
    'appointments',
    'availability',
    'notifications',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'medsync.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.unread_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'medsync.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'

# ---------------------------------------------------------------------------
# Email — Brevo SMTP
# ---------------------------------------------------------------------------
# Fully environment-driven, so switching provider is a .env edit and never a code
# change. Defaults target Brevo's SMTP relay; Mailtrap, Resend and Gmail all work
# through the same variables — see .env.example.
#
# Brevo is the choice here because it verifies a single *sender address* rather than
# requiring a domain you own, so real delivery works from a personal address.
#
# The default *backend* stays the console, so a fresh clone runs the whole
# verification flow with no credentials at all — emails print to the runserver
# terminal. Set EMAIL_BACKEND in .env to send over SMTP.
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp-relay.brevo.com')
# int() because Django's SMTP backend wants a number, and provider docs usually
# quote the port as a string — passing that through unconverted bites you at
# connection time rather than at startup.
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
# No default: Brevo's SMTP login is account-specific, unlike Mailtrap's fixed 'api'.
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'MedSync <no-reply@medsync.local>')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'support@medsync.local')

# Guard against a half-configured SMTP setup silently failing at signup time:
# choosing an SMTP backend without credentials is a configuration error, not a
# runtime one, so surface it at startup rather than at the first send.
if EMAIL_BACKEND.endswith('smtp.EmailBackend') and not (EMAIL_HOST_USER and EMAIL_HOST_PASSWORD):
    import warnings
    warnings.warn(
        'EMAIL_BACKEND is set to SMTP but EMAIL_HOST_USER / EMAIL_HOST_PASSWORD are '
        'empty. For Brevo these are the SMTP login and SMTP key from '
        'SMTP & API -> SMTP. Emails will fail to send. Set them in .env, or unset '
        'EMAIL_BACKEND to fall back to the console backend.',
        RuntimeWarning,
    )

# Outer bound on signed tokens. Verification links are additionally held to 24h by
# EmailVerification.EXPIRY_SECONDS, and password reset links to 1h by
# PasswordResetToken.is_expired() — those tighter, per-flow windows are what
# actually governs.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24

# Session
SESSION_COOKIE_AGE = 86400 * 7  # 7 days
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

"""Transactional email for the accounts app.

Single place where verification and password-reset mail is composed and sent, used
by both the doctor and the patient flows (req1 §12 — only the copy differs per
role, never the mechanism).

Two deliberate choices:

* No ``fail_silently``. The previous implementation swallowed SMTP errors, so a
  misconfigured host produced a signup that looked successful but sent nothing.
  Failures are logged and reported back to the caller, which surfaces an honest
  message to the user.
* Nothing sensitive in the payload. No passwords, no medical data, and the token
  is the only secret in the URL (req1 §11).
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from .tokens import email_verification_token, encode_uid

logger = logging.getLogger(__name__)

VERIFICATION_SUBJECT = 'Verify your MedSync email address'
PASSWORD_RESET_SUBJECT = 'Reset your MedSync password'


def _send(subject, to_email, text_template, html_template, context):
    """Render and send one multipart email. Returns True on success.

    Never raises: callers decide what the user sees, and an SMTP outage must not
    turn into a 500 on a signup that otherwise succeeded.
    """
    # Read at call time, not import time, so a settings override (or a later env
    # change) is picked up rather than frozen at first import.
    context.setdefault('support_email', getattr(settings, 'SUPPORT_EMAIL', ''))
    try:
        text_body = render_to_string(text_template, context)
        html_body = render_to_string(html_template, context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        message.attach_alternative(html_body, 'text/html')
        message.send(fail_silently=False)
        return True
    except Exception:
        # Log the failure and the recipient, never the credentials (req1 §11).
        logger.exception('Failed to send %r to %s', subject, to_email)
        return False


def build_verification_url(user, request):
    """Absolute, HTTPS-ready verification URL for `user`.

    `build_absolute_uri` inherits the scheme from the incoming request, so this is
    http:// in local development and https:// behind a TLS-terminating proxy with
    SECURE_PROXY_SSL_HEADER set — no hard-coded host or scheme.
    """
    path = reverse('accounts:verify_email', kwargs={
        'uidb64': encode_uid(user),
        'token': email_verification_token.make_token(user),
    })
    return request.build_absolute_uri(path)


def send_verification_email(user, request):
    """Send the 'verify your address' email. Returns True on success."""
    context = {
        'user': user,
        'verification_url': build_verification_url(user, request),
        'expiry_hours': 24,
        'role_label': 'doctor' if user.is_doctor else 'patient',
    }
    return _send(
        subject=VERIFICATION_SUBJECT,
        to_email=user.email,
        text_template='emails/verification.txt',
        html_template='emails/verification.html',
        context=context,
    )


def send_password_reset_email(user, request, reset_token):
    """Send the password-reset link. `reset_token` is a PasswordResetToken row."""
    path = reverse('accounts:reset_password', kwargs={'token': reset_token.token})
    context = {
        'user': user,
        'reset_url': request.build_absolute_uri(path),
        'expiry_minutes': 60,
    }
    return _send(
        subject=PASSWORD_RESET_SUBJECT,
        to_email=user.email,
        text_template='emails/password_reset.txt',
        html_template='emails/password_reset.html',
        context=context,
    )

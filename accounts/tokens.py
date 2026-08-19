"""Signed, single-purpose tokens for email verification.

req1 §2 forbids tokens derived predictably from user id / email / timestamp, and
asks for Django's built-in signing machinery. `PasswordResetTokenGenerator` is
exactly that: an HMAC over a per-purpose salt, `SECRET_KEY` and a hash of
user-specific state. It is not guessable without `SECRET_KEY`.

Subclassing (rather than reusing `default_token_generator`) gives a distinct
`key_salt`, so a verification token can never be replayed against the password
reset flow and vice versa.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes, force_str


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = 'accounts.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        # Including is_verified means the token stops working the moment the
        # account is verified, so a leaked link cannot be replayed. Including the
        # email means changing the address invalidates any link sent to the old
        # one.
        return f'{user.pk}{user.email}{user.is_verified}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()


def encode_uid(user):
    """URL-safe base64 of the user pk, for the <uidb64> URL segment."""
    return urlsafe_base64_encode(force_bytes(user.pk))


def decode_uid(uidb64):
    """Reverse of `encode_uid`, returning the pk as a string, or None.

    Never raises, and never returns a non-numeric value. Both matter: a bad uid is
    an ordinary invalid-link case, so the view must render the friendly
    'link expired or invalid' page rather than a 500 or a stack trace (req1 §5).

    The digit check is the important part — a uid like 'YWJj' decodes cleanly to
    'abc', and passing that to `filter(pk='abc')` raises ValueError from the field
    itself, well past any decoding guard.
    """
    try:
        decoded = force_str(urlsafe_base64_decode(uidb64))
    except (TypeError, ValueError, OverflowError, UnicodeDecodeError):
        return None
    return decoded if decoded.isdigit() else None

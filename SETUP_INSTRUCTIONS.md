# MedSync — Setup & Run Instructions

## Installation

### 1. Navigate to the project directory
```bash
cd C:\Users\HP\Desktop\MedSync
```

### 2. Create a virtual environment
```bash
python -m venv venv
```

### 3. Activate it
```bash
venv\Scripts\activate
```

### 4. Install dependencies
```bash
pip install -r pip_requirements.txt
```

### 5. Configure the environment
```bash
copy .env.example .env
```
You can run everything without editing `.env` — see **Email** below.

### 6. Run migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 7. (Optional) Create a superuser
```bash
python manage.py createsuperuser
```

### 8. Run the development server
```bash
python manage.py runserver
```

Open **http://127.0.0.1:8000/**

---

## Email

All email settings come from environment variables, so switching provider is a
`.env` edit and never a code change.

### Stage 1 — local development (no credentials needed)

`EMAIL_BACKEND` is left unset by default, which selects Django's console backend.
Verification and password-reset emails print straight to the `runserver` terminal.
Copy the link out of the terminal and paste it into your browser — the entire
verification flow is testable this way without an account at any provider.

### Stage 2 — real delivery via Brevo

Brevo verifies a single **sender address** rather than requiring a domain you own,
so real delivery works from a personal address.

1. Create a Brevo account and verify your sender address under
   **Senders, Domains & Dedicated IPs → Senders** — confirm the link Brevo emails
   you. Until that sender is verified, Brevo rejects every send, and this is the
   most common cause of a failure here.
2. Open **SMTP & API → SMTP** and copy your **SMTP login** and **SMTP key**. The key
   is *not* your Brevo account password.
3. Fill in `.env`:

```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<your SMTP login>
EMAIL_HOST_PASSWORD=<your SMTP key>
DEFAULT_FROM_EMAIL=MedSync <your-verified-sender@example.com>
```

`DEFAULT_FROM_EMAIL` must be the sender you verified. Authenticate your sending
domain in Brevo later for better deliverability.

If you set the SMTP backend but leave the credentials empty, Django prints a startup
warning rather than failing silently at signup.

Brevo's free tier has a daily send cap. While iterating on forms rather than on
email, comment out `EMAIL_BACKEND` so mail prints to the terminal instead.

**Mailtrap**, **Resend** and **Gmail** work through the same variables —
`.env.example` has each block commented out. Note that Mailtrap's live sending
requires a domain you own (a `@gmail.com` sender is rejected), and its sandbox
captures mail without delivering it to anyone.

Never commit `.env`.

---

## Testing

```bash
python manage.py test accounts
```

Covers signup for both roles, verification tokens (valid, invalid, malformed,
expired, replayed), login gating for unverified accounts, resend rate limiting,
account-enumeration resistance, password reset, duplicate email, the phone
country-code round trip, and a render check on every public and auth page.

---

## Architecture notes

### Design system

`templates/base.html` defines the shared component classes — `.form-input`,
`.form-select`, `.btn-primary`, `.card`, `.status-*` and friends — inside:

```html
<style type="text/tailwindcss"> ... </style>
```

**That `type` attribute is required.** The project loads Tailwind through the Play
CDN, which only compiles `@apply` inside `type="text/tailwindcss"`. In a plain
`<style>` block the browser treats `@apply` as an unknown at-rule and drops it, so
every rule silently produces zero declarations — which is what previously left form
inputs unpadded and unaligned across the whole app.

Every form control is a fixed **44px** (`h-11`). An explicit height is what makes
`<input>`, `<select>` and `<input type="date">` actually line up: their intrinsic
heights differ, so padding alone leaves rows like the phone group misaligned. 44px
is also a comfortable touch target.

The Play CDN is a development tool and logs a production warning. Adding a real
build step (or committing compiled CSS) is the eventual fix.

### Reusable form partials

`templates/partials/` holds the pieces every auth form is built from, so label
spacing, control height, width, radius, focus ring and error styling are identical
by construction rather than by copy-paste:

| Partial | Purpose |
|---|---|
| `text_field.html` | text / email / date / tel input |
| `select_field.html` | select, height-matched to inputs |
| `password_field.html` | input plus the in-input visibility toggle |
| `phone_field.html` | country select + national number as one component |
| `form_errors.html` | form-level (non-field) error summary |
| `public_nav.html`, `public_footer.html` | shared public-site chrome |

Password toggles are driven by one delegated handler in `base.html` keyed on
`[data-password-toggle]`, so each toggle acts only on the input inside its own
`.password-input-wrapper` and every field toggles independently.

### Phone numbers

The country selector is a real form field (`country_code`, keyed on ISO 3166-1
alpha-2 codes), and the visible input holds only the **national** number. The
server combines them into E.164 once, at save time, in
`PhoneFieldMixin.get_e164()`.

This matters: the previous version had JavaScript rewrite the input to `+234…` on
submit, so a validation error re-rendered an already-prefixed value and the next
submit prefixed it again — producing `+2342348012345678`. ISO codes rather than
dial codes as option values also matter, because Canada and the US share `+1`, and
duplicate option values would make the browser silently snap the user's choice to
whichever appeared last.

Countries live in `accounts/countries.py`; flag emoji are derived from the ISO code
rather than typed by hand.

### Email verification

| Piece | Location |
|---|---|
| Signed token generator | `accounts/tokens.py` |
| Composition and sending | `accounts/emails.py` |
| Email templates | `templates/emails/` |
| Verification state + resend throttle | `EmailVerification` in `accounts/models.py` |
| Flow views | `accounts/views.py` |

Tokens are HMACs built on Django's `PasswordResetTokenGenerator` with a
verification-specific `key_salt`, so a reset token can't be replayed as a
verification token. `user.is_verified` and `user.email` are part of the hash, which
makes each link single-use and invalidates any link sent to a since-changed
address. Links live at `/accounts/verify-email/<uidb64>/<token>/` and expire after
24 hours; password reset links expire after 1 hour and can be used once.

A verification email goes out on **signup and on any sign-in attempt by an
unverified account**, so a user never has to know to press "resend" — the auto-send
respects the same throttle, so the login form can't be used as an unlimited mailer.

**Verification gates sign-in, not signup.** Registering logs the user straight into
their dashboard; the link is sent immediately so it's waiting in the inbox by the
time they next sign in, which is the point at which a missing verification starts
to block them. The practical consequence worth knowing: a user who never verifies
keeps working until they log out, then cannot get back in until they do.

Opening a valid link **signs the user in and redirects them to their dashboard**
(doctor or patient). Opening the link proves control of the mailbox, which is a
stronger claim than a password alone, so this is a deliberate choice rather than a
shortcut. One consequence worth knowing: anyone holding the link gets a session, so
a forwarded email hands over access until the link is spent.

An already-verified link is the exception — it redirects to the login page and
signs nobody in. That branch runs *before* the token is checked, and `uidb64` is
only base64 of the primary key, so auto-login there would let anyone hijack any
verified account by walking ids. `accounts/tests.py` guards this.

Resend is capped at 3 per hour per account with a 60-second cooldown, tracked on
the `EmailVerification` row rather than in the cache so the limit survives a
restart. The verification pages show a live countdown on the resend button while
the cooldown runs; the server enforces the limit regardless of what the client
does with the button.

Verification links issued by the older UUID scheme still resolve, via the legacy
`/accounts/<role>/verify/<uuid>/` route.

### Appointment notifications

Every appointment change emails **both** the doctor and the patient, whichever of
them made it, and writes an in-app notification for each. All of it goes through
`appointments/notify.py` — `notify_booked`, `notify_rescheduled`,
`notify_cancelled`, `notify_completed` — rather than views calling
`create_notification` directly, so the email and the in-app record can't drift
apart and neither party can be silently left out.

Emails carry doctor, patient, date, time, duration, type and status, plus the
cancellation or reschedule reason. They deliberately **omit `notes` and
`doctor_notes`**: those are free-text fields that can hold clinical detail, and
email is a less private channel than the app. Recipients get a link to the
appointment page instead. Reasons are included because both parties can already
read them in-app and they're operationally necessary.

A send failure is logged and swallowed — an SMTP outage must not roll back an
appointment that was already saved.

### Country-based booking

A patient can only book a doctor whose `User.country` matches their own. Location
comes from the country chosen at signup, stored in its own column rather than
parsed back out of the phone number (a saved `+1` is both the US and Canada).

The rule lives in `appointments/scoping.py` (`bookable_doctors_for`,
`patients_bookable_by`, `can_book`) and is applied in four places, because hiding a
doctor from a list is presentation only and `/patient/book/<id>/` is guessable:

| Where | What it does |
|---|---|
| `find_doctor` | lists same-country doctors only |
| `book_appointment` | refuses a cross-country pairing outright |
| `AppointmentForm` | narrows the patient *queryset*, not just the dropdown |
| `schedule_appointment` | offers same-country patients only |

A blank country on either side excludes the pairing rather than matching
everything — two people can't be confirmed to share a location if one has none
recorded. Accounts predating the field therefore see nobody until their owner picks
a country, which both profile pages now offer. `find_doctor` distinguishes the
three reasons a list can be empty (no country set, no match for the filters, no
doctors in that country yet) so the fix is always obvious.

No data migration guesses country from existing phone numbers; that would silently
invent locations for `+1`.



Anonymous endpoints respond identically whether or not an address is registered:

- Forgot password and anonymous resend always say *"If an account exists for that
  email address…"*.
- Login reports one generic *"Invalid email or password"* for an unknown address, a
  wrong password, **and** the right password on the other role's account.

Signup is the deliberate exception: it reports *"An account with this email already
exists."* because a registration form is unusable otherwise.

---

## Key routes

| Route | Purpose |
|---|---|
| `/accounts/doctor/signup/` · `/accounts/patient/signup/` | Registration |
| `/accounts/doctor/login/` · `/accounts/patient/login/` | Sign in |
| `/accounts/doctor/forgot-password/` · `/accounts/patient/forgot-password/` | Role-scoped reset request |
| `/accounts/verify-email/sent/` | "Check your email" after signup |
| `/accounts/verify-email/<uidb64>/<token>/` | Verify an account |
| `/accounts/verify-email/required/` | Blocking page for unverified sign-in |
| `/accounts/verify-email/resend/` | Rate-limited resend |
| `/accounts/verify-email/change-email/` | Fix a mistyped address pre-verification |
| `/about/` · `/how-it-works/` · `/contact/` · `/faq/` | Public pages |

---

## Manual test walkthrough

### Doctor signup and verification
1. Go to `/accounts/doctor/signup/` and submit the form.
2. You land straight on the doctor dashboard — signup does not gate on verification.
3. A verification email is already in your inbox (or the `runserver` terminal on the
   console backend). Open it and you're returned to the dashboard, now verified.
4. If you skip step 3, log out and try to sign in: that's where it blocks you.

### Unverified sign-in
1. Sign up but don't open the link, then log out.
2. Sign in with the correct password.
3. You get the **Verify your email** page — no dashboard access — and a fresh link
   is sent automatically. The resend button counts down before it re-enables.
4. Opening that link signs you in and lands you on your dashboard.

### Appointment emails
Book an appointment as a patient. Both the patient and the doctor addresses should
receive "Appointment confirmed". Cancel it and both get "Appointment cancelled" with
the reason. Check that the notes you typed at booking are *not* in either email.

### Country matching
Sign up a doctor with one country and a patient with another. The patient's Find
Doctor page should not list that doctor, and visiting
`/patient/book/<that doctor's id>/` directly should bounce back with an explanation.
Set both to the same country and the doctor appears.

### Resend rate limiting
The resend button is disabled while the countdown runs. Three sends in an hour
exhausts the quota, after which further requests are refused until the window
rolls over. Repeated sign-in attempts are throttled the same way — the second and
third attempt inside a minute send nothing.

### Duplicate email
Sign up twice with the same address — the second attempt shows *"An account with
this email already exists."* under the email field.

### Password toggles
On any page with two password fields, toggle one and confirm the other is
unaffected. Check the icon swaps between eye and eye-off, and that clicking it
never submits the form.

### Phone field
Pick a country and type digits — grouping follows the country. Submit with a
deliberate error elsewhere in the form and confirm your country and digits are both
still there, un-prefixed.

---

## Troubleshooting

**Emails aren't appearing anywhere.** With no `EMAIL_BACKEND` in `.env` they print
to the `runserver` terminal, not to an inbox. That's expected in Stage 1.

**Brevo rejects the message.** Your `DEFAULT_FROM_EMAIL` must be a sender Brevo has
verified, and `EMAIL_HOST_PASSWORD` must be the SMTP key, not your account
password.

**Form inputs look unstyled.** Check that `base.html` still has
`<style type="text/tailwindcss">`. Without the `type` attribute the entire design
system compiles to nothing.

**Static files not loading.** Run `python manage.py collectstatic`.

**Database errors after a model change.** Run `makemigrations` then `migrate`.
Deleting `db.sqlite3` and re-migrating also works, but discards all data.

import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.shortcuts import render, redirect

from .forms import ContactForm

logger = logging.getLogger(__name__)

# Content for the FAQ page. Kept as data rather than markup so the template renders
# every entry identically and adding a question is a one-line change.
FAQ_GROUPS = [
    {
        'title': 'Getting started',
        'items': [
            {
                'q': 'Is MedSync free to use?',
                'a': 'Yes — creating an account and booking or managing appointments '
                     'is completely free, for both doctors and patients.',
            },
            {
                'q': 'Do I need to verify my email address?',
                'a': 'Yes. After signing up we send a verification link to your '
                     'address, and you will need to open it before you can sign in. '
                     'The link is valid for 24 hours, and you can request a new one '
                     'from the sign-in page at any time.',
            },
            {
                'q': 'I never received my verification email. What now?',
                'a': 'Check your spam or junk folder first. If it is not there, use '
                     'the "Resend verification email" option — and if the address you '
                     'signed up with had a typo in it, you can correct it and we will '
                     'send a fresh link to the new address.',
            },
            {
                'q': 'Do I need separate doctor and patient accounts?',
                'a': 'Each account has one role, chosen at signup, so a doctor account '
                     'and a patient account are separate. Sign in through the door that '
                     'matches your account — the login pages link to each other.',
            },
        ],
    },
    {
        'title': 'For doctors',
        'items': [
            {
                'q': 'How do I set my availability?',
                'a': 'From the Availability page you can set working hours for each day '
                     'of the week, add break periods, choose your appointment length and '
                     'buffer time, and block specific dates.',
            },
            {
                'q': 'Can I book an appointment on a patient\'s behalf?',
                'a': 'Yes. Use Schedule Appointment from your dashboard to pick the '
                     'patient, date, time and appointment type, and add any notes.',
            },
            {
                'q': 'What happens when I cancel or reschedule?',
                'a': 'Cancelling asks for a reason, and both cancellations and '
                     'reschedules notify the patient. The history page keeps the '
                     'original and final times so the change is always traceable.',
            },
        ],
    },
    {
        'title': 'For patients',
        'items': [
            {
                'q': 'How do I book an appointment?',
                'a': 'Choose a doctor, pick an appointment type, then select a date and '
                     'time. Only slots the doctor genuinely has open are offered, so you '
                     'cannot land on one that is already taken.',
            },
            {
                'q': 'Can I reschedule or cancel myself?',
                'a': 'Yes — both are available from your dashboard or the appointment '
                     'detail page, subject to your doctor\'s policy. You will be asked '
                     'to confirm before anything changes.',
            },
            {
                'q': 'Why are there no times available on the date I want?',
                'a': 'Either the doctor is not working that day or every slot is already '
                     'booked. The booking screen will suggest choosing another date.',
            },
        ],
    },
    {
        'title': 'Account and security',
        'items': [
            {
                'q': 'I forgot my password.',
                'a': 'Use the "Forgot password?" link on your sign-in page. We will '
                     'email you a reset link that is valid for one hour and can be used '
                     'once. We will never send you your existing password.',
            },
            {
                'q': 'How do I change my password?',
                'a': 'Open Settings while signed in and use the Change Password form. '
                     'You will be signed out afterwards and will need to sign in again '
                     'with the new password.',
            },
            {
                'q': 'Is my data secure?',
                'a': 'Passwords are stored hashed, never in plain text, and are never '
                     'sent by email. Verification and reset links are signed, expire, '
                     'and contain no personal or medical information.',
            },
        ],
    },
]


def landing(request):
    return render(request, 'core/landing.html')


def about(request):
    return render(request, 'core/about.html')


def how_it_works(request):
    return render(request, 'core/how_it_works.html')


def contact(request):
    """Public contact form. Delivers to SUPPORT_EMAIL via the configured backend.

    With the default console backend the message prints to the runserver terminal,
    which is the same development story as the verification emails.
    """
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            subject_label = dict(ContactForm.SUBJECT_CHOICES)[data['subject']]
            try:
                EmailMessage(
                    subject=f'[MedSync contact] {subject_label}',
                    body=(
                        f'From: {data["name"]} <{data["email"]}>\n'
                        f'Topic: {subject_label}\n\n'
                        f'{data["message"]}\n'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[settings.SUPPORT_EMAIL],
                    # So a support reply goes to the sender, not to the from-address.
                    reply_to=[data['email']],
                ).send(fail_silently=False)
            except Exception:
                logger.exception('Contact form delivery failed')
                messages.error(
                    request,
                    'We could not send your message just now. Please try again, or '
                    f'email us directly at {settings.SUPPORT_EMAIL}.',
                )
            else:
                messages.success(
                    request,
                    'Thanks for getting in touch — we\'ll reply to your email shortly.',
                )
                return redirect('core:contact')
    else:
        form = ContactForm()

    return render(request, 'core/contact.html', {
        'form': form,
        'support_email': settings.SUPPORT_EMAIL,
    })


def faq(request):
    return render(request, 'core/faq.html', {'faq_groups': FAQ_GROUPS})

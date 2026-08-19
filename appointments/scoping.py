"""Who may book whom.

One home for the country-matching rule, because it has to hold in four places —
the doctor listing, the patient-side booking view, the doctor's scheduling form
queryset, and the patient dropdown on that form. Kept out of the view modules so
`forms.py` can import it without a cycle (the view modules import `forms`).

The rule: a patient and a doctor can only be paired if `User.country` matches on
both sides. Location comes from the country chosen at signup, not the doctor's
free-text `location` field, which is unvalidated.

A blank country on either side excludes the pairing rather than matching
everything — two people can't be confirmed to share a location if one of them has
none recorded. Accounts predating the country field therefore see nobody until
their owner sets one from their profile page. That is the safe direction to fail,
and the affected screens say so explicitly instead of showing a bare empty list.
"""

from accounts.models import User


def bookable_doctors_for(patient):
    """Doctors `patient` may book. Empty queryset when their country is unset."""
    if not patient.country:
        return User.objects.none()
    return (
        User.objects.filter(role='doctor', is_active=True, country=patient.country)
        .select_related('doctor_profile')
    )


def patients_bookable_by(doctor):
    """Patients `doctor` may schedule for. Empty queryset when country is unset."""
    if not doctor.country:
        return User.objects.none()
    return User.objects.filter(role='patient', is_active=True, country=doctor.country)


def can_book(patient, doctor):
    """True when this pairing is permitted."""
    return bool(patient.country) and patient.country == doctor.country

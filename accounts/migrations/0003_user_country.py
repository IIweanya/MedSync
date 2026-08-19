"""Adds User.country (ISO 3166-1 alpha-2).

Blank-able rather than defaulted, so existing accounts migrate untouched. A blank
country means "location unknown", which the booking filter treats as not-matching
rather than matching-everything — the owner sets theirs from their profile page.
Deliberately no data migration guessing country from stored phone numbers: '+1' maps
to both the US and Canada, so a backfill would silently invent locations.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_emailverification_resend_throttle'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='country',
            field=models.CharField(blank=True, max_length=2),
        ),
    ]

"""Adds resend-throttle state to EmailVerification.

Purely additive: every new column is nullable or has a default, so existing rows
(and the existing unverified account in the development database) migrate without
needing a data step and keep their current verification status.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailverification',
            name='last_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='emailverification',
            name='resend_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='emailverification',
            name='resend_window_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

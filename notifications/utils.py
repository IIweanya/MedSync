from .models import Notification


def create_notification(user, notification_type, title, message, appointment=None):
    """Helper to create a notification for a user."""
    Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        appointment=appointment,
    )

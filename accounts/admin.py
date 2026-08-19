from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, DoctorProfile, PatientProfile, EmailVerification, PasswordResetToken


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'full_name', 'role', 'is_verified', 'is_active', 'date_joined']
    list_filter = ['role', 'is_verified', 'is_active']
    search_fields = ['email', 'full_name']
    ordering = ['-date_joined']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('full_name', 'phone', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_verified', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'role', 'password1', 'password2'),
        }),
    )


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'specialty', 'license_id']
    search_fields = ['user__email', 'user__full_name']


@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'date_of_birth']
    search_fields = ['user__email', 'user__full_name']


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    """Read-mostly view of verification state, useful for support ('did their email
    actually go out, and are they rate-limited?')."""

    list_display = ['user', 'created_at', 'last_sent_at', 'resend_count', 'is_expired']
    search_fields = ['user__email']
    readonly_fields = ['created_at']

    @admin.display(boolean=True, description='Expired')
    def is_expired(self, obj):
        return obj.is_expired()


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'created_at', 'used', 'is_expired']
    list_filter = ['used']
    search_fields = ['user__email']
    readonly_fields = ['created_at']

    @admin.display(boolean=True, description='Expired')
    def is_expired(self, obj):
        return obj.is_expired()

from django.contrib import admin
from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['doctor', 'patient', 'date', 'start_time', 'appointment_type', 'status']
    list_filter = ['status', 'appointment_type', 'date']
    search_fields = ['doctor__full_name', 'patient__full_name']
    date_hierarchy = 'date'
    ordering = ['-date', '-start_time']

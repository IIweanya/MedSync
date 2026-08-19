from django.urls import path
from . import doctor_views

urlpatterns = [
    path('dashboard/', doctor_views.doctor_dashboard, name='doctor_dashboard'),
    path('appointments/', doctor_views.doctor_appointments, name='doctor_appointments'),
    path('appointments/<int:pk>/', doctor_views.appointment_detail, name='doctor_appointment_detail'),
    path('appointments/<int:pk>/reschedule/', doctor_views.reschedule_appointment, name='doctor_reschedule'),
    path('appointments/<int:pk>/confirm/', doctor_views.confirm_appointment, name='doctor_confirm'),
    path('appointments/<int:pk>/cancel/', doctor_views.cancel_appointment, name='doctor_cancel'),
    path('appointments/<int:pk>/complete/', doctor_views.complete_appointment, name='doctor_complete'),
    path('appointments/schedule/', doctor_views.schedule_appointment, name='doctor_schedule_appointment'),
    path('calendar/', doctor_views.doctor_calendar, name='doctor_calendar'),
    path('patients/', doctor_views.doctor_patients, name='doctor_patients'),
    path('patients/<int:patient_id>/', doctor_views.patient_details_for_doctor, name='doctor_patient_details'),
    path('history/', doctor_views.doctor_history, name='doctor_history'),
]

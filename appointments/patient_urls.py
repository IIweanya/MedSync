from django.urls import path
from . import patient_views

urlpatterns = [
    path('dashboard/', patient_views.patient_dashboard, name='patient_dashboard'),
    path('find-doctor/', patient_views.find_doctor, name='find_doctor'),
    path('book/<int:doctor_id>/', patient_views.book_appointment, name='book_appointment'),
    path('appointments/', patient_views.patient_appointments, name='patient_appointments'),
    path('appointments/<int:pk>/', patient_views.patient_appointment_detail, name='patient_appointment_detail'),
    path('appointments/<int:pk>/reschedule/', patient_views.patient_reschedule, name='patient_reschedule'),
    path('appointments/<int:pk>/cancel/', patient_views.patient_cancel, name='patient_cancel'),
    path('calendar/', patient_views.patient_calendar, name='patient_calendar'),
    path('history/', patient_views.patient_history, name='patient_history'),
]

from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Doctor auth
    path('doctor/signup/', views.doctor_signup, name='doctor_signup'),
    path('doctor/login/', views.doctor_login, name='doctor_login'),
    path('doctor/forgot-password/', views.forgot_password, {'role': 'doctor'},
         name='doctor_forgot_password'),

    # Patient auth
    path('patient/signup/', views.patient_signup, name='patient_signup'),
    path('patient/login/', views.patient_login, name='patient_login'),
    path('patient/forgot-password/', views.forgot_password, {'role': 'patient'},
         name='patient_forgot_password'),

    # Email verification. Static segments are listed before the token pattern so
    # intent is obvious on reading; they cannot collide in any case, since
    # <uidb64>/<token> needs two path segments and these have one.
    path('verify-email/sent/', views.verify_email_sent, name='verify_email_sent'),
    path('verify-email/required/', views.verify_email_required, name='verify_email_required'),
    path('verify-email/resend/', views.resend_verification, name='resend_verification'),
    path('verify-email/change-email/', views.change_email, name='change_email'),
    path('verify-email/<str:uidb64>/<str:token>/', views.verify_email, name='verify_email'),

    # Legacy UUID verification links, kept working for emails already delivered.
    path('doctor/verify/<uuid:token>/', views.verify_email_legacy, name='verify_email_legacy'),
    path('patient/verify/<uuid:token>/', views.verify_email_legacy,
         name='patient_verify_email_legacy'),

    # Shared
    path('login/', views.login_choice, name='login'),
     path('logout/', views.logout_view, name='logout'),
     path('delete/', views.delete_account_and_logout, name='delete_account'),
     path('delete/confirm/', views.confirm_delete, name='confirm_delete'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password/<uuid:token>/', views.reset_password, name='reset_password'),
    path('profile/', views.profile_view, name='profile_view'),
    path('settings/', views.settings_view, name='settings_view'),
]

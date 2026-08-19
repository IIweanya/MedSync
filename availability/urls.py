from django.urls import path
from . import views

urlpatterns = [
    path('', views.availability_view, name='doctor_availability'),
    path('exception/<int:pk>/delete/', views.delete_exception, name='delete_exception'),
]

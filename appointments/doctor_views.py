from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Appointment
from .forms import AppointmentForm, ConfirmAppointmentForm, RescheduleForm, CancelForm
from accounts.models import User, DoctorProfile, PatientProfile
from .notify import (
    notify_booked, notify_cancelled, notify_completed, notify_confirmed,
    notify_rescheduled,
)
from .scoping import patients_bookable_by


def doctor_required(view_func):
    """Decorator: ensure the logged-in user is a doctor."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_doctor:
            messages.error(request, 'Access denied.')
            return redirect('core:landing')
        return view_func(request, *args, **kwargs)
    return wrapper


@doctor_required
def doctor_dashboard(request):
    user = request.user
    today = timezone.now().date()

    today_appointments = Appointment.objects.filter(
        doctor=user, date=today
    ).exclude(status=Appointment.CANCELLED).order_by('start_time')

    upcoming = Appointment.objects.filter(
        doctor=user, date__gt=today,
        status__in=[Appointment.UPCOMING, Appointment.CONFIRMED]
    ).order_by('date', 'start_time')[:5]

    # Stats
    total_patients = Appointment.objects.filter(doctor=user).values('patient').distinct().count()
    completed_count = Appointment.objects.filter(doctor=user, status=Appointment.COMPLETED).count()
    cancelled_count = Appointment.objects.filter(doctor=user, status=Appointment.CANCELLED).count()
    upcoming_count = Appointment.objects.filter(
        doctor=user, date__gte=today,
        status__in=[Appointment.UPCOMING, Appointment.CONFIRMED]
    ).count()

    context = {
        'today_appointments': today_appointments,
        'upcoming_appointments': upcoming,
        'total_patients': total_patients,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
        'upcoming_count': upcoming_count,
        'today': today,
    }
    return render(request, 'doctor/dashboard.html', context)


@doctor_required
def doctor_appointments(request):
    user = request.user
    appointments = Appointment.objects.filter(doctor=user).select_related('patient')

    # Filters
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('q')

    if status:
        appointments = appointments.filter(status=status)
    if date_from:
        appointments = appointments.filter(date__gte=date_from)
    if date_to:
        appointments = appointments.filter(date__lte=date_to)
    if search:
        appointments = appointments.filter(
            Q(patient__full_name__icontains=search) |
            Q(appointment_type__icontains=search)
        )

    context = {
        'appointments': appointments.order_by('-date', '-start_time'),
        'status_choices': Appointment.STATUS_CHOICES,
        'selected_status': status,
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'doctor/appointments.html', context)


@doctor_required
def appointment_detail(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, doctor=request.user)
    return render(request, 'doctor/appointment_detail.html', {'appointment': appointment})


@doctor_required
def schedule_appointment(request):
    if request.method == 'POST':
        form = AppointmentForm(request.POST, doctor=request.user)
        if form.is_valid():
            appt = form.save(commit=False)
            appt.doctor = request.user
            appt.created_by = 'doctor'
            appt.status = Appointment.CONFIRMED
            # Auto-calculate end_time from doctor profile duration if not provided
            if not appt.end_time:
                try:
                    duration = request.user.doctor_profile.appointment_duration
                    dt_start = datetime.combine(appt.date, appt.start_time)
                    appt.end_time = (dt_start + timedelta(minutes=duration)).time()
                except Exception:
                    pass
            appt.save()

            # Notifies and emails both the patient and the doctor.
            notify_booked(appt, request, booked_by_doctor=True)
            messages.success(request, 'Appointment scheduled. Both of you have been emailed.')
            return redirect('doctor_appointment_detail', pk=appt.pk)
    else:
        form = AppointmentForm(doctor=request.user)

    # Same-country patients only, mirroring the restriction on patient-side booking
    # so a doctor can't be handed a patient they could never be booked by.
    patients = patients_bookable_by(request.user).order_by('full_name')
    return render(request, 'doctor/schedule_appointment.html', {
        'form': form,
        'patients': patients,
        'doctor_country_label': request.user.country_label,
    })

@doctor_required
def reschedule_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, doctor=request.user)
    if appointment.status in [Appointment.COMPLETED, Appointment.CANCELLED]:
        messages.error(request, 'Cannot reschedule this appointment.')
        return redirect('doctor_appointment_detail', pk=pk)

    if request.method == 'POST':
        form = RescheduleForm(request.POST)
        if form.is_valid():
            # Create new appointment as rescheduled copy
            new_appt = Appointment.objects.create(
                doctor=appointment.doctor,
                patient=appointment.patient,
                date=form.cleaned_data['date'],
                start_time=form.cleaned_data['start_time'],
                end_time=appointment.end_time,
                appointment_type=appointment.appointment_type,
                notes=appointment.notes,
                status=Appointment.CONFIRMED,
                rescheduled_from=appointment,
                created_by='doctor',
                reschedule_reason=form.cleaned_data.get('reason', ''),
            )
            # Mark original as rescheduled
            appointment.status = Appointment.RESCHEDULED
            appointment.reschedule_reason = form.cleaned_data.get('reason', '')
            appointment.save()

            notify_rescheduled(new_appt, appointment, request, rescheduled_by_doctor=True)
            messages.success(request, 'Appointment rescheduled. Both of you have been emailed.')
            return redirect('doctor_appointment_detail', pk=new_appt.pk)
    else:
        form = RescheduleForm(initial={'date': appointment.date, 'start_time': appointment.start_time})

    return render(request, 'doctor/reschedule_appointment.html', {'form': form, 'appointment': appointment})


@doctor_required
def cancel_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, doctor=request.user)
    if appointment.status in [Appointment.COMPLETED, Appointment.CANCELLED]:
        messages.error(request, 'Cannot cancel this appointment.')
        return redirect('doctor_appointment_detail', pk=pk)

    if request.method == 'POST':
        form = CancelForm(request.POST)
        if form.is_valid():
            appointment.status = Appointment.CANCELLED
            appointment.cancel_reason = form.cleaned_data['reason']
            appointment.save()

            notify_cancelled(appointment, request, cancelled_by_doctor=True)
            messages.success(request, 'Appointment cancelled. Both of you have been emailed.')
            return redirect('doctor_appointments')
    else:
        form = CancelForm()

    return render(request, 'doctor/cancel_appointment.html', {'form': form, 'appointment': appointment})


@doctor_required
def confirm_appointment(request, pk):
    """Doctor sets the final day and time, then confirms.

    A patient's booking records the slot they *asked* for; this is where the doctor
    decides what actually happens. The form is pre-filled with the request, so
    accepting it unchanged is a single click, and changing it emails the patient the
    shift explicitly.
    """
    appointment = get_object_or_404(Appointment, pk=pk, doctor=request.user)
    if appointment.status in [Appointment.COMPLETED, Appointment.CANCELLED,
                              Appointment.RESCHEDULED]:
        messages.error(request, 'This appointment can no longer be confirmed.')
        return redirect('doctor_appointment_detail', pk=pk)

    # Held before the form can overwrite them, so the email can name the original.
    requested_date = appointment.date
    requested_time = appointment.start_time

    if request.method == 'POST':
        form = ConfirmAppointmentForm(request.POST)
        if form.is_valid():
            appointment.date = form.cleaned_data['date']
            appointment.start_time = form.cleaned_data['start_time']
            try:
                duration = request.user.doctor_profile.appointment_duration
            except Exception:
                duration = 30
            dt_start = datetime.combine(appointment.date, appointment.start_time)
            appointment.end_time = (dt_start + timedelta(minutes=duration)).time()
            appointment.status = Appointment.CONFIRMED
            appointment.save()

            notify_confirmed(appointment, request,
                             requested_date=requested_date,
                             requested_time=requested_time)
            messages.success(request, 'Appointment confirmed. The patient has been emailed.')
            return redirect('doctor_appointment_detail', pk=pk)
    else:
        form = ConfirmAppointmentForm(initial={
            'date': appointment.date,
            'start_time': appointment.start_time,
        })

    return render(request, 'doctor/confirm_appointment.html', {
        'form': form,
        'appointment': appointment,
    })


@doctor_required
def complete_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, doctor=request.user)
    if request.method == 'POST':
        appointment.status = Appointment.COMPLETED
        appointment.doctor_notes = request.POST.get('doctor_notes', '')
        appointment.save()
        notify_completed(appointment, request)
        messages.success(request, 'Appointment marked as completed.')
    return redirect('doctor_appointment_detail', pk=pk)


@doctor_required
def doctor_calendar(request):
    user = request.user
    today = timezone.now().date()
    appointments = Appointment.objects.filter(
        doctor=user
    ).exclude(status=Appointment.CANCELLED).values(
        'id', 'date', 'start_time', 'end_time', 'status',
        'appointment_type', 'patient__full_name'
    )

    import json
    events = []
    for a in appointments:
        color_map = {
            'upcoming': '#3B82F6',
            'confirmed': '#10B981',
            'completed': '#6B7280',
            'rescheduled': '#F59E0B',
            'no_show': '#EF4444',
        }
        events.append({
            'id': a['id'],
            'title': a['patient__full_name'],
            'start': f"{a['date']}T{a['start_time']}",
            'end': f"{a['date']}T{a['end_time']}",
            'color': color_map.get(a['status'], '#6B7280'),
            'url': f"/doctor/appointments/{a['id']}/",
        })

    return render(request, 'doctor/calendar.html', {
        'events_json': json.dumps(events),
        'today': today.isoformat(),
    })


@doctor_required
def doctor_patients(request):
    user = request.user
    search = request.GET.get('q', '')

    patient_ids = Appointment.objects.filter(
        doctor=user
    ).values_list('patient', flat=True).distinct()

    from accounts.models import User as AppUser
    patients = AppUser.objects.filter(pk__in=patient_ids).select_related('patient_profile')

    if search:
        patients = patients.filter(
            Q(full_name__icontains=search) | Q(email__icontains=search)
        )

    # Annotate with last/next appointment
    enriched = []
    for patient in patients:
        last_appt = Appointment.objects.filter(
            doctor=user, patient=patient, status=Appointment.COMPLETED
        ).order_by('-date').first()
        next_appt = Appointment.objects.filter(
            doctor=user, patient=patient,
            date__gte=timezone.now().date(),
            status__in=[Appointment.UPCOMING, Appointment.CONFIRMED]
        ).order_by('date').first()
        enriched.append({'patient': patient, 'last_appt': last_appt, 'next_appt': next_appt})

    return render(request, 'doctor/patients.html', {
        'patients': enriched, 'search': search
    })


@doctor_required
def patient_details_for_doctor(request, patient_id):
    from accounts.models import User as AppUser
    patient = get_object_or_404(AppUser, pk=patient_id, role='patient')
    appointments = Appointment.objects.filter(
        doctor=request.user, patient=patient
    ).order_by('-date', '-start_time')
    return render(request, 'doctor/patient_details.html', {
        'patient': patient,
        'appointments': appointments,
    })


@doctor_required
def doctor_history(request):
    user = request.user
    tab = request.GET.get('tab', 'all')
    search = request.GET.get('q', '')

    appointments = Appointment.objects.filter(
        doctor=user,
        status__in=[Appointment.COMPLETED, Appointment.CANCELLED, Appointment.RESCHEDULED, Appointment.NO_SHOW]
    ).select_related('patient').order_by('-date', '-start_time')

    if tab != 'all':
        appointments = appointments.filter(status=tab)
    if search:
        appointments = appointments.filter(patient__full_name__icontains=search)

    return render(request, 'doctor/history.html', {
        'appointments': appointments, 'tab': tab, 'search': search,
    })

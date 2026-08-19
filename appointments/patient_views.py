from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Appointment
from .forms import PatientBookingForm, RescheduleForm, CancelForm
from .notify import notify_booked, notify_cancelled, notify_rescheduled
from .scoping import bookable_doctors_for, can_book
from accounts.models import User, DoctorProfile


def patient_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_patient:
            messages.error(request, 'Access denied.')
            return redirect('core:landing')
        return view_func(request, *args, **kwargs)
    return wrapper


@patient_required
def patient_dashboard(request):
    user = request.user
    today = timezone.now().date()

    next_appt = Appointment.objects.filter(
        patient=user,
        date__gte=today,
        status__in=[Appointment.UPCOMING, Appointment.CONFIRMED]
    ).order_by('date', 'start_time').first()

    upcoming = Appointment.objects.filter(
        patient=user,
        date__gte=today,
        status__in=[Appointment.UPCOMING, Appointment.CONFIRMED]
    ).order_by('date', 'start_time')[:5]

    completed_count = Appointment.objects.filter(patient=user, status=Appointment.COMPLETED).count()
    cancelled_count = Appointment.objects.filter(patient=user, status=Appointment.CANCELLED).count()
    upcoming_count = Appointment.objects.filter(
        patient=user, date__gte=today,
        status__in=[Appointment.UPCOMING, Appointment.CONFIRMED]
    ).count()

    recent_activity = Appointment.objects.filter(patient=user).order_by('-updated_at')[:5]

    context = {
        'next_appointment': next_appt,
        'upcoming_appointments': upcoming,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
        'upcoming_count': upcoming_count,
        'recent_activity': recent_activity,
        'today': today,
    }
    return render(request, 'patient/dashboard.html', context)


@patient_required
def find_doctor(request):
    """Step 1 of booking: choose a doctor.

    Only doctors in the patient's own country are listed — see
    `bookable_doctors_for`.
    """
    specialty = request.GET.get('specialty', '')
    search = request.GET.get('q', '')

    doctors = bookable_doctors_for(request.user)

    if specialty:
        doctors = doctors.filter(doctor_profile__specialty=specialty)
    if search:
        doctors = doctors.filter(
            Q(full_name__icontains=search) |
            Q(doctor_profile__specialty__icontains=search) |
            Q(doctor_profile__location__icontains=search)
        )

    context = {
        'doctors': doctors,
        'specialty_choices': DoctorProfile.SPECIALTY_CHOICES,
        'selected_specialty': specialty,
        'search': search,
        # Lets the template explain an empty list: no country set is a different
        # problem from no doctors in your country, and needs a different fix.
        'patient_country': request.user.country,
        'patient_country_label': request.user.country_label,
    }
    return render(request, 'patient/find_doctor.html', context)


@patient_required
def book_appointment(request, doctor_id):
    """Multi-step booking flow: type → date → time → confirm."""
    doctor = get_object_or_404(User, pk=doctor_id, role='doctor')

    # Enforced here as well as in the listing: hiding a doctor from find_doctor is
    # presentation, and this URL is guessable by id.
    if not can_book(request.user, doctor):
        if not request.user.country:
            messages.error(
                request,
                'Set your country on your profile before booking — MedSync matches '
                'you with doctors in your own country.',
            )
            return redirect('accounts:profile_view')
        messages.error(
            request,
            f'{doctor.display_name} is not available for booking in '
            f'{request.user.country_label}.',
        )
        return redirect('find_doctor')

    step = request.GET.get('step', '1')

    if request.method == 'POST':
        appointment_type = request.POST.get('appointment_type')
        date_str = request.POST.get('date')
        start_time_str = request.POST.get('start_time')
        notes = request.POST.get('notes', '')

        if not all([appointment_type, date_str, start_time_str]):
            messages.error(request, 'Please complete all steps.')
            return redirect(f'/patient/book/{doctor_id}/?step=1')

        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            messages.error(request, 'Invalid date or time.')
            return redirect(f'/patient/book/{doctor_id}/?step=1')

        # Calculate end time
        try:
            duration = doctor.doctor_profile.appointment_duration
        except Exception:
            duration = 30
        dt_start = datetime.combine(date, start_time)
        end_time = (dt_start + timedelta(minutes=duration)).time()

        appt = Appointment.objects.create(
            doctor=doctor,
            patient=request.user,
            date=date,
            start_time=start_time,
            end_time=end_time,
            appointment_type=appointment_type,
            notes=notes,
            status=Appointment.UPCOMING,
            created_by='patient',
        )

        # Notifies and emails both the patient and the doctor.
        notify_booked(appt, request)

        messages.success(
            request,
            'Appointment requested. Your doctor will confirm the day and time, and '
            'we have emailed you the details.',
        )
        return redirect('patient_appointment_detail', pk=appt.pk)

    # GET — show booking form
    available_slots = _get_available_slots(doctor, request.GET.get('date'))
    context = {
        'doctor': doctor,
        'step': step,
        'appointment_types': Appointment.TYPE_CHOICES,
        'selected_date': request.GET.get('date', ''),
        'available_slots': available_slots,
    }
    return render(request, 'patient/book_appointment.html', context)


def _get_available_slots(doctor, date_str):
    """Return list of available time strings for a given doctor and date."""
    if not date_str:
        return []
    try:
        from datetime import date as date_cls
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return []

    if date < timezone.now().date():
        return []

    day_of_week = date.weekday()

    try:
        avail = doctor.weekly_availability.get(day_of_week=day_of_week, is_active=True)
    except Exception:
        return []

    try:
        duration = doctor.doctor_profile.appointment_duration
        buffer = doctor.doctor_profile.buffer_time
    except Exception:
        duration, buffer = 30, 10

    slot_length = duration + buffer
    slots = []
    current = datetime.combine(date, avail.start_time)
    end = datetime.combine(date, avail.end_time)

    while current + timedelta(minutes=duration) <= end:
        slot_time = current.time()
        # Check if already booked
        booked = Appointment.objects.filter(
            doctor=doctor,
            date=date,
            start_time=slot_time,
        ).exclude(status__in=[Appointment.CANCELLED, Appointment.RESCHEDULED]).exists()
        if not booked:
            slots.append(slot_time.strftime('%H:%M'))
        current += timedelta(minutes=slot_length)

    return slots


@patient_required
def patient_appointments(request):
    user = request.user
    status = request.GET.get('status')
    search = request.GET.get('q', '')

    appointments = Appointment.objects.filter(patient=user).select_related('doctor', 'doctor__doctor_profile')

    if status:
        appointments = appointments.filter(status=status)
    if search:
        appointments = appointments.filter(
            Q(doctor__full_name__icontains=search) |
            Q(doctor__doctor_profile__specialty__icontains=search)
        )

    context = {
        'appointments': appointments.order_by('-date', '-start_time'),
        'status_choices': Appointment.STATUS_CHOICES,
        'selected_status': status,
        'search': search,
    }
    return render(request, 'patient/appointments.html', context)


@patient_required
def patient_appointment_detail(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=request.user)
    return render(request, 'patient/appointment_detail.html', {'appointment': appointment})


@patient_required
def patient_reschedule(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=request.user)
    if appointment.status in [Appointment.COMPLETED, Appointment.CANCELLED]:
        messages.error(request, 'Cannot reschedule this appointment.')
        return redirect('patient_appointment_detail', pk=pk)

    if request.method == 'POST':
        form = RescheduleForm(request.POST)
        if form.is_valid():
            new_appt = Appointment.objects.create(
                doctor=appointment.doctor,
                patient=appointment.patient,
                date=form.cleaned_data['date'],
                start_time=form.cleaned_data['start_time'],
                end_time=appointment.end_time,
                appointment_type=appointment.appointment_type,
                notes=appointment.notes,
                status=Appointment.UPCOMING,
                rescheduled_from=appointment,
                created_by='patient',
                reschedule_reason=form.cleaned_data.get('reason', ''),
            )
            appointment.status = Appointment.RESCHEDULED
            appointment.reschedule_reason = form.cleaned_data.get('reason', '')
            appointment.save()

            notify_rescheduled(new_appt, appointment, request)
            messages.success(request, 'Appointment rescheduled. Both of you have been emailed.')
            return redirect('patient_appointment_detail', pk=new_appt.pk)
    else:
        form = RescheduleForm(initial={'date': appointment.date, 'start_time': appointment.start_time})

    available_slots = _get_available_slots(appointment.doctor, request.GET.get('date', str(appointment.date)))
    return render(request, 'patient/reschedule_appointment.html', {
        'form': form,
        'appointment': appointment,
        'available_slots': available_slots,
    })


@patient_required
def patient_cancel(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=request.user)
    if appointment.status in [Appointment.COMPLETED, Appointment.CANCELLED]:
        messages.error(request, 'Cannot cancel this appointment.')
        return redirect('patient_appointment_detail', pk=pk)

    if request.method == 'POST':
        form = CancelForm(request.POST)
        if form.is_valid():
            appointment.status = Appointment.CANCELLED
            appointment.cancel_reason = form.cleaned_data['reason']
            appointment.save()

            notify_cancelled(appointment, request)
            messages.success(request, 'Appointment cancelled. Both of you have been emailed.')
            return redirect('patient_appointments')
    else:
        form = CancelForm()

    return render(request, 'patient/cancel_appointment.html', {'form': form, 'appointment': appointment})


@patient_required
def patient_calendar(request):
    user = request.user
    appointments = Appointment.objects.filter(patient=user).values(
        'id', 'date', 'start_time', 'end_time', 'status',
        'appointment_type', 'doctor__full_name'
    )

    import json
    color_map = {
        'upcoming': '#3B82F6',
        'confirmed': '#10B981',
        'completed': '#6B7280',
        'cancelled': '#EF4444',
        'rescheduled': '#F59E0B',
        'no_show': '#FBBF24',
    }
    events = [
        {
            'id': a['id'],
            'title': f"Dr. {a['doctor__full_name']}",
            'start': f"{a['date']}T{a['start_time']}",
            'end': f"{a['date']}T{a['end_time']}",
            'color': color_map.get(a['status'], '#6B7280'),
            'url': f"/patient/appointments/{a['id']}/",
        }
        for a in appointments
    ]

    return render(request, 'patient/calendar.html', {
        'events_json': json.dumps(events),
        'today': timezone.now().date().isoformat(),
    })


@patient_required
def patient_history(request):
    user = request.user
    tab = request.GET.get('tab', 'all')
    search = request.GET.get('q', '')

    appointments = Appointment.objects.filter(
        patient=user,
        status__in=[Appointment.COMPLETED, Appointment.CANCELLED, Appointment.RESCHEDULED, Appointment.NO_SHOW]
    ).select_related('doctor', 'doctor__doctor_profile').order_by('-date', '-start_time')

    if tab != 'all':
        appointments = appointments.filter(status=tab)
    if search:
        appointments = appointments.filter(doctor__full_name__icontains=search)

    return render(request, 'patient/history.html', {
        'appointments': appointments, 'tab': tab, 'search': search,
    })

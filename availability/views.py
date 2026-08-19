from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import WeeklyAvailability, AvailabilityException
from .forms import WeeklyAvailabilityFormSet, AvailabilityExceptionForm


def doctor_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_doctor:
            messages.error(request, 'Access denied.')
            return redirect('core:landing')
        return view_func(request, *args, **kwargs)
    return wrapper


@doctor_required
def availability_view(request):
    user = request.user
    weekly = {a.day_of_week: a for a in user.weekly_availability.all()}
    exceptions = user.availability_exceptions.order_by('date')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_weekly':
            for day in range(7):
                start = request.POST.get(f'start_{day}')
                end = request.POST.get(f'end_{day}')
                is_active = request.POST.get(f'active_{day}') == 'on'

                if start and end:
                    WeeklyAvailability.objects.update_or_create(
                        doctor=user,
                        day_of_week=day,
                        defaults={'start_time': start, 'end_time': end, 'is_active': is_active},
                    )
                else:
                    WeeklyAvailability.objects.filter(doctor=user, day_of_week=day).update(is_active=False)

            messages.success(request, 'Weekly availability saved.')
            return redirect('doctor_availability')

        elif action == 'add_exception':
            form = AvailabilityExceptionForm(request.POST)
            if form.is_valid():
                exc = form.save(commit=False)
                exc.doctor = user
                exc.save()
                messages.success(request, 'Time block added.')
                return redirect('doctor_availability')
        else:
            messages.error(request, 'Unknown action.')

    # Build day data for template
    days = []
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for i, name in enumerate(day_names):
        avail = weekly.get(i)
        days.append({
            'index': i,
            'name': name,
            'avail': avail,
        })

    context = {
        'days': days,
        'exceptions': exceptions,
        'exception_form': AvailabilityExceptionForm(),
    }
    return render(request, 'doctor/availability.html', context)


@doctor_required
def delete_exception(request, pk):
    exc = get_object_or_404(AvailabilityException, pk=pk, doctor=request.user)
    exc.delete()
    messages.success(request, 'Time block removed.')
    return redirect('doctor_availability')

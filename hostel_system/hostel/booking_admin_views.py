from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .booking import CannotConfirm, cancel_booking, confirm_booking
from .decorators import staff_required
from .models import Booking


@staff_required
def bookings_list(request):
    bookings = Booking.objects.select_related("room").order_by("-created_at")
    return render(request, "hostel/bookings.html", {"bookings": bookings})


@staff_required
@require_POST
def confirm_booking_page(request, booking_id):
    get_object_or_404(Booking, id=booking_id)
    try:
        tenant = confirm_booking(booking_id)
    except CannotConfirm as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            f"{tenant.full_name} is now a tenant in room {tenant.room.room_number}.",
        )
    return redirect("bookings")


@login_required
@require_POST
def cancel_booking_page(request, booking_id):
    get_object_or_404(Booking, id=booking_id)

    # The manager can cancel any booking.A student can cancel only their own.
    student = None if request.user.is_staff else request.user
    if cancel_booking(booking_id, student=student):
        messages.success(request, "Booking cancelled.The bed is free again.")
    else:
        messages.error(request, "That booking cannot be cancelled.")

    if request.user.is_staff:
        return redirect("bookings")
    return redirect("book_rooms")
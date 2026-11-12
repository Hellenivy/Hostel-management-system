from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render

from .booking import AlreadyBooked, RoomFull, beds_taken, book_room
from .forms import BookingForm
from .models import Booking, Room, Tenant


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("book_rooms")
    else:
        form = UserCreationForm()
    return render(request, "hostel/register.html", {"form": form})


@login_required
def book_rooms(request):
    # Admins manage rooms elsewhere; tenants already have a room.
    if request.user.is_staff:
        return redirect("dashboard")
    if Tenant.objects.filter(user=request.user).exists():
        return redirect("my_account")

    my_booking = Booking.objects.filter(student=request.user, status="Reserved").first()

    rooms = []
    for room in Room.objects.order_by("room_number"):
        rooms.append({"room": room, "free": room.capacity - beds_taken(room)})

    return render(request, "hostel/book_rooms.html", {
        "rooms": rooms,
        "my_booking": my_booking,
    })


@login_required
def book_room_page(request, room_id):
    if request.user.is_staff:
        return redirect("dashboard")

    room = get_object_or_404(Room, id=room_id)

    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            try:
                book_room(student=request.user, room_id=room.id, **form.cleaned_data)
            except (RoomFull, AlreadyBooked) as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    f"Room {room.room_number} is booked for you. "
                    "The manager will confirm it.",
                )
            return redirect("book_rooms")
    else:
        form = BookingForm()

    return render(request, "hostel/book_room.html", {
        "form": form,
        "room": room,
        "free": room.capacity - beds_taken(room),
    })
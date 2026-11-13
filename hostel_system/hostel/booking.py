from django.db import transaction
from django.db.models import F

from .models import Booking, Room, Tenant


class RoomFull(Exception):
    pass


class AlreadyBooked(Exception):
    pass

def beds_taken(room, ignore_tenant=None):
    # A bed is taken by a tenant who lives here or by a student who booked it.
    tenants = Tenant.objects.filter(room=room, move_out_date__isnull=True)
    if ignore_tenant is not None and ignore_tenant.pk:
        tenants = tenants.exclude(pk=ignore_tenant.pk)
    reserved = Booking.objects.filter(room=room, status="Reserved").count()
    return tenants.count() + reserved


def book_room(student, room_id, full_name, phone, id_number, move_in_date):
    with transaction.atomic():
        # 1. Lock the room first. Writing to the room makes everyone else who
        #    wants this room wait here until we have finished.
        Room.objects.filter(id=room_id).update(capacity=F("capacity"))
        room = Room.objects.get(id=room_id)

        # 2. Now it is safe to count, because nobody else can book at this moment.
        if Booking.objects.filter(student=student, status="Reserved").exists():
            raise AlreadyBooked("You already have a booking.")

        if beds_taken(room) >= room.capacity:
            raise RoomFull(f"Room {room.room_number} is full.")

        # 3. Save the booking.
        return Booking.objects.create(
            student=student,
            room=room,
            full_name=full_name,
            phone=phone,
            id_number=id_number,
            move_in_date=move_in_date,
        )



class CannotConfirm(Exception):
    pass


def confirm_booking(booking_id):
    with transaction.atomic():
        # Lock the booking first,so two clicks can never confirm it twice.
        Booking.objects.filter(id=booking_id).update(status=F("status"))
        booking = Booking.objects.get(id=booking_id)

        if booking.status != "Reserved":
            raise CannotConfirm(f"This booking is already {booking.status.lower()}.")

        if Tenant.objects.filter(id_number__iexact=booking.id_number).exists():
            raise CannotConfirm("A tenant with this ID number already exists.")

        if Tenant.objects.filter(user=booking.student).exists():
            raise CannotConfirm("This student is already a tenant.")

        tenant = Tenant.objects.create(
            full_name=booking.full_name,
            phone=booking.phone,
            id_number=booking.id_number,
            room=booking.room,
            move_in_date=booking.move_in_date,
            user=booking.student,
        )
        booking.status = "Confirmed"
        booking.save()
        return tenant


def cancel_booking(booking_id, student=None):
    # Pass a student to make sure they can only cancel their own booking.
    bookings = Booking.objects.filter(id=booking_id, status="Reserved")
    if student is not None:
        bookings = bookings.filter(student=student)
    return bookings.update(status="Cancelled") > 0



def save_tenant_form(form_class, data, instance=None):
    # Check and save a tenant form while the room is locked, so two admins
    # adding tenants at the same moment cannot both take the last bed.
    with transaction.atomic():
        room_id = data.get("room")
        if room_id and str(room_id).isdigit():
            Room.objects.filter(id=room_id).update(capacity=F("capacity"))

        form = form_class(data, instance=instance)
        if form.is_valid():
            form.save()
        return form
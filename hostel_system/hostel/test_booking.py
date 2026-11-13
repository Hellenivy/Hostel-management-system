from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase,TransactionTestCase
from .booking import (
    AlreadyBooked,CannotConfirm,RoomFull,beds_taken,book_room,confirm_booking,
)
from .forms import TenantForm
from .models import Room,Tenant


def make_student(name):
    return get_user_model().objects.create_user(name, password="pass12345")


def book(student, room):
    return book_room(
        student=student,
        room_id=room.id,
        full_name="Test Student",
        phone="0712345678",
        id_number="ID" + student.username,
        move_in_date=date(2026, 12, 1),
    )


class SimpleBookingTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(
            room_number="101", rent_amount=Decimal("5000"), capacity=2
        )

    def test_a_booking_takes_one_bed(self):
        book(make_student("anna"), self.room)
        self.assertEqual(beds_taken(self.room), 1)

    def test_the_third_student_is_refused_in_a_two_bed_room(self):
        book(make_student("anna"), self.room)
        book(make_student("brian"), self.room)
        with self.assertRaises(RoomFull):
            book(make_student("carol"), self.room)
        self.assertEqual(beds_taken(self.room), 2)

    def test_one_student_cannot_book_twice(self):
        anna = make_student("anna")
        book(anna, self.room)
        with self.assertRaises(AlreadyBooked):
            book(anna, self.room)



class StudentPageTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(
            room_number="101", rent_amount=Decimal("5000"), capacity=1
        )

    def booking_data(self):
        return {
            "full_name": "Jane Student",
            "phone": "0733000111",
            "id_number": "30303030",
            "move_in_date": "2026-12-05",
        }

    def test_a_student_can_register_and_is_logged_in(self):
        response = self.client.post("/register/", {
            "username": "jane",
            "password1": "Str0ng-pass-99",
            "password2": "Str0ng-pass-99",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="jane").exists())
        self.assertEqual(self.client.get("/book/").status_code, 200)

    def test_the_rooms_page_shows_free_beds(self):
        self.client.force_login(make_student("jane"))
        self.assertContains(self.client.get("/book/"), "1 of 1 free")

    def test_a_student_books_a_room(self):
        self.client.force_login(make_student("jane"))
        response = self.client.post(f"/book/{self.room.id}/", self.booking_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(beds_taken(self.room), 1)
        self.assertContains(self.client.get("/book/"), "You have booked room 101")

    def test_a_bad_phone_number_is_not_accepted(self):
        self.client.force_login(make_student("jane"))
        data = self.booking_data()
        data["phone"] = "123"
        response = self.client.post(f"/book/{self.room.id}/", data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(beds_taken(self.room), 0)

    def test_a_full_room_cannot_be_booked(self):
        book(make_student("first"), self.room)
        self.client.force_login(make_student("late"))
        self.client.post(f"/book/{self.room.id}/", self.booking_data())
        self.assertEqual(beds_taken(self.room), 1)

    def test_a_student_who_is_not_a_tenant_is_sent_to_the_booking_page(self):
        self.client.force_login(make_student("jane"))
        response = self.client.get("/my/")
        self.assertRedirects(response, "/book/")

    def test_admins_do_not_use_the_booking_pages(self):
        admin = get_user_model().objects.create_user("boss", password="x", is_staff=True)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get("/book/"), "/")

class ConfirmAndCancelTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(
            room_number="101", rent_amount=Decimal("5000"), capacity=2
        )
        self.admin = get_user_model().objects.create_user(
            "boss", password="pass12345", is_staff=True
        )

    def test_confirming_makes_the_student_a_tenant(self):
        student = make_student("anna")
        booking = book(student, self.room)
        self.client.force_login(self.admin)
        self.client.post(f"/bookings/{booking.id}/confirm/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Confirmed")
        tenant = Tenant.objects.get(user=student)
        self.assertEqual(tenant.room, self.room)
        self.assertEqual(tenant.full_name, "Test Student")
        # The bed is now used by the tenant, not by the booking.
        self.assertEqual(beds_taken(self.room), 1)

    def test_confirming_twice_makes_only_one_tenant(self):
        booking = book(make_student("anna"), self.room)
        self.client.force_login(self.admin)
        self.client.post(f"/bookings/{booking.id}/confirm/")
        self.client.post(f"/bookings/{booking.id}/confirm/")
        self.assertEqual(Tenant.objects.count(), 1)

    def test_an_id_number_that_already_exists_is_refused(self):
        booking = book(make_student("anna"), self.room)
        Tenant.objects.create(
            full_name="Old", phone="0711111111", id_number=booking.id_number,
            room=self.room, move_in_date=date(2026, 1, 1),
        )
        with self.assertRaises(CannotConfirm):
            confirm_booking(booking.id)

    def test_cancelling_frees_the_bed(self):
        booking = book(make_student("anna"), self.room)
        self.client.force_login(self.admin)
        self.client.post(f"/bookings/{booking.id}/cancel/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Cancelled")
        self.assertEqual(beds_taken(self.room), 0)

    def test_a_student_can_cancel_their_own_booking(self):
        anna = make_student("anna")
        booking = book(anna, self.room)
        self.client.force_login(anna)
        self.client.post(f"/bookings/{booking.id}/cancel/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Cancelled")

    def test_a_student_cannot_cancel_someone_elses_booking(self):
        booking = book(make_student("anna"), self.room)
        self.client.force_login(make_student("brian"))
        self.client.post(f"/bookings/{booking.id}/cancel/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Reserved")

    def test_a_student_cannot_confirm_a_booking(self):
        booking = book(make_student("anna"), self.room)
        self.client.force_login(make_student("brian"))
        self.client.post(f"/bookings/{booking.id}/confirm/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Reserved")
        self.assertEqual(Tenant.objects.count(), 0)

    def test_the_bookings_page_lists_bookings(self):
        book(make_student("anna"), self.room)
        self.client.force_login(self.admin)
        response = self.client.get("/bookings/")
        self.assertContains(response, "Test Student")
        self.assertContains(response, "Confirm")



class AddTenantAndBookingsTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(
            room_number="101", rent_amount=Decimal("5000"), capacity=1
        )
        self.admin = get_user_model().objects.create_user(
            "boss", password="pass12345", is_staff=True
        )

    def tenant_data(self, **changes):
        data = {
            "full_name": "Walk In", "phone": "0722000111",
            "id_number": "55555555", "room": self.room.pk,
            "move_in_date": "2026-12-01",
        }
        data.update(changes)
        return data

    def test_add_tenant_form_counts_booked_beds(self):
        book(make_student("anna"), self.room)
        form = TenantForm(self.tenant_data())
        self.assertFalse(form.is_valid())
        self.assertIn("room", form.errors)

    def test_add_tenant_works_when_a_bed_is_free(self):
        self.assertTrue(TenantForm(self.tenant_data()).is_valid())

    def test_editing_a_tenant_in_a_full_room_still_works(self):
        tenant = Tenant.objects.create(
            full_name="Old", phone="0711111111", id_number="11111111",
            room=self.room, move_in_date=date(2026, 1, 1),
        )
        form = TenantForm(
            self.tenant_data(full_name="Renamed", id_number="11111111"),
            instance=tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_room_with_a_booking_cannot_be_deleted(self):
        book(make_student("anna"), self.room)
        self.client.force_login(self.admin)
        self.client.post(f"/rooms/{self.room.id}/delete/")
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())

    def test_the_dashboard_shows_booked_beds(self):
        book(make_student("anna"), self.room)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/"), "1 booked")


class TwoAdminsAtOnceTests(TransactionTestCase):
    def test_two_admins_cannot_put_two_tenants_in_a_one_bed_room(self):
        import threading
        import time

        from django.db import OperationalError, connection

        from .booking import save_tenant_form

        room = Room.objects.create(
            room_number="202", rent_amount=Decimal("5000"), capacity=1
        )
        start_together = threading.Barrier(2)
        results = []

        def admin_adds(number):
            try:
                start_together.wait(timeout=10)
                for attempt in range(10):
                    try:
                        form = save_tenant_form(TenantForm, {
                            "full_name": f"Tenant {number}", "phone": "0712345678",
                            "id_number": f"7700{number}", "room": room.pk,
                            "move_in_date": "2026-12-01",
                        })
                        results.append("refused" if form.errors else "saved")
                        return
                    except OperationalError:
                        time.sleep(0.05 * (attempt + 1))
            finally:
                connection.close()

        threads = [threading.Thread(target=admin_adds, args=(n,)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(results), ["refused", "saved"])
        self.assertEqual(Tenant.objects.filter(room=room).count(), 1)
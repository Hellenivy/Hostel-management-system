from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .booking import AlreadyBooked, RoomFull, beds_taken, book_room
from .models import Room


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
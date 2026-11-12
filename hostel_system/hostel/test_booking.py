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
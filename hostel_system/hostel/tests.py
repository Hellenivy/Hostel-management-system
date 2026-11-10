import json
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from .forms import PaymentForm, TenantForm
from .models import MpesaTransaction, Payment, Room, Tenant
from .mpesa import format_phone_number
from .views import mpesa_callback, rent_summary

TODAY = date(2026, 11, 9)


def make_room(number="101", rent="5000", capacity=1):
    return Room.objects.create(
        room_number=number, rent_amount=Decimal(rent), capacity=capacity
    )


def make_tenant(room, move_in=date(2026, 10, 15), name="Anna Wanjiku",
                phone="0712345678", id_number="12345678"):
    return Tenant.objects.create(
        full_name=name, phone=phone, id_number=id_number,
        room=room, move_in_date=move_in,
    )


def pay(tenant, amount):
    return Payment.objects.create(tenant=tenant, amount=Decimal(str(amount)))


# ---------- Phone number formatting (STK Push and SMS) ----------

class PhoneFormatTests(TestCase):
    def test_zero_prefix_becomes_254(self):
        self.assertEqual(format_phone_number("0712345678"), "254712345678")

    def test_plus_and_spaces_are_removed(self):
        self.assertEqual(format_phone_number("+254 712 345 678"), "254712345678")

    def test_nine_digit_number_gets_254(self):
        self.assertEqual(format_phone_number("712345678"), "254712345678")

    def test_01_numbers_are_accepted(self):
        self.assertEqual(format_phone_number("0110123456"), "254110123456")

    def test_invalid_numbers_return_none(self):
        for bad in ["12345", "", "0812345678", "abc"]:
            self.assertIsNone(format_phone_number(bad), bad)


# ---------- Monthly rent balance ----------

@patch("django.utils.timezone.localdate", return_value=TODAY)
class MonthlyBalanceTests(TestCase):
    def setUp(self):
        self.room = make_room(rent="5000")

    def test_two_months_billed_when_moved_in_last_month(self, _):
        tenant = make_tenant(self.room, move_in=date(2026, 10, 15))
        self.assertEqual(tenant.months_billed(), 2)
        self.assertEqual(tenant.balance(), Decimal("10000"))

    def test_one_month_billed_when_moved_in_this_month(self, _):
        tenant = make_tenant(self.room, move_in=date(2026, 11, 1))
        self.assertEqual(tenant.balance(), Decimal("5000"))

    def test_payment_reduces_balance(self, _):
        tenant = make_tenant(self.room)
        pay(tenant, 5000)
        self.assertEqual(tenant.balance(), Decimal("5000"))

    def test_paid_up_balance_is_zero(self, _):
        tenant = make_tenant(self.room)
        pay(tenant, 10000)
        self.assertEqual(tenant.balance(), Decimal("0"))

    def test_overpayment_gives_negative_balance(self, _):
        tenant = make_tenant(self.room)
        pay(tenant, 12000)
        self.assertEqual(tenant.balance(), Decimal("-2000"))

    def test_future_move_in_is_not_billed_yet(self, _):
        tenant = make_tenant(self.room, move_in=date(2026, 12, 1))
        self.assertEqual(tenant.balance(), Decimal("0"))

    def test_tenant_without_room_owes_nothing(self, _):
        tenant = make_tenant(self.room)
        tenant.room = None
        tenant.save()
        self.assertEqual(tenant.balance(), Decimal("0"))

    def test_views_and_model_give_the_same_balance(self, _):
        tenant = make_tenant(self.room)
        pay(tenant, 3000)
        self.assertEqual(rent_summary(tenant)["balance"], tenant.balance())


# ---------- Tenant form: capacity, ID number, phone ----------

class TenantFormTests(TestCase):
    def setUp(self):
        self.room = make_room(capacity=1)

    def data(self, **overrides):
        base = {
            "full_name": "New Tenant",
            "phone": "0722000111",
            "id_number": "99999999",
            "room": self.room.pk,
            "move_in_date": "2026-11-01",
        }
        base.update(overrides)
        return base

    def test_valid_tenant_is_accepted(self):
        self.assertTrue(TenantForm(self.data()).is_valid())

    def test_full_room_is_rejected(self):
        make_tenant(self.room)
        form = TenantForm(self.data())
        self.assertFalse(form.is_valid())
        self.assertIn("room", form.errors)

    def test_editing_a_tenant_in_a_full_room_is_allowed(self):
        tenant = make_tenant(self.room)
        form = TenantForm(
            self.data(full_name="Renamed", id_number=tenant.id_number),
            instance=tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_duplicate_id_number_is_rejected(self):
        other_room = make_room("102")
        make_tenant(other_room, id_number="12345678")
        form = TenantForm(self.data(id_number="12345678"))
        self.assertFalse(form.is_valid())
        self.assertIn("id_number", form.errors)

    def test_invalid_phone_is_rejected(self):
        form = TenantForm(self.data(phone="12345"))
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)


# ---------- Manual payment form ----------

class PaymentFormTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant(make_room())

    def data(self, **overrides):
        base = {"tenant": self.tenant.pk, "amount": "1000", "mpesa_code": ""}
        base.update(overrides)
        return base

    def test_valid_payment_is_accepted(self):
        self.assertTrue(PaymentForm(self.data()).is_valid())

    def test_zero_amount_is_rejected(self):
        self.assertFalse(PaymentForm(self.data(amount="0")).is_valid())

    def test_negative_amount_is_rejected(self):
        self.assertFalse(PaymentForm(self.data(amount="-500")).is_valid())

    def test_mpesa_code_is_saved_in_capitals(self):
        form = PaymentForm(self.data(mpesa_code=" abc123xyz "))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["mpesa_code"], "ABC123XYZ")

    def test_duplicate_mpesa_code_is_rejected(self):
        Payment.objects.create(
            tenant=self.tenant, amount=Decimal("1000"), mpesa_code="ABC123XYZ"
        )
        form = PaymentForm(self.data(mpesa_code="abc123xyz"))
        self.assertFalse(form.is_valid())


# ---------- M-Pesa callback ----------

@override_settings(MPESA_CALLBACK_TOKEN="test-token")
class MpesaCallbackTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tenant = make_tenant(make_room())
        self.txn = MpesaTransaction.objects.create(
            tenant=self.tenant,
            amount=Decimal("5000"),
            checkout_request_id="ws_CO_TEST_1",
            status="Pending",
        )

    def post(self, payload, token="test-token"):
        request = self.factory.post(
            f"/mpesa/callback/{token}/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return mpesa_callback(request, token)

    def success_payload(self, amount=5000, receipt="QWE123RTY4"):
        return {"Body": {"stkCallback": {
            "CheckoutRequestID": "ws_CO_TEST_1",
            "ResultCode": 0,
            "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
            ]},
        }}}

    def test_wrong_token_is_rejected(self):
        from django.http import Http404
        with self.assertRaises(Http404):
            self.post(self.success_payload(), token="wrong")
        self.assertEqual(Payment.objects.count(), 0)

    def test_successful_callback_records_one_payment(self):
        self.post(self.success_payload())
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "Success")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Payment.objects.first().mpesa_code, "QWE123RTY4")

    def test_repeated_callback_does_not_duplicate_payment(self):
        self.post(self.success_payload())
        self.post(self.success_payload())
        self.assertEqual(Payment.objects.count(), 1)

    def test_cancelled_payment_is_marked_failed(self):
        payload = {"Body": {"stkCallback": {
            "CheckoutRequestID": "ws_CO_TEST_1", "ResultCode": 1032,
        }}}
        self.post(payload)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "Failed")
        self.assertEqual(Payment.objects.count(), 0)

    def test_amount_mismatch_records_no_payment(self):
        self.post(self.success_payload(amount=4000))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "Pending")
        self.assertEqual(Payment.objects.count(), 0)


# ---------- Rent-due SMS reminders ----------

@override_settings(
    RENT_DUE_DAY=1,
    RENT_REMINDER_DAYS_BEFORE=3,
    MPESA_SHORTCODE="174379",
)
class RentReminderTests(TestCase):
    def run_command(self, run_date):
        out = StringIO()
        call_command(
            "send_rent_reminders", dry_run=True, date=run_date,
            stdout=out, stderr=StringIO(),
        )
        return out.getvalue()

    @patch("django.utils.timezone.localdate", return_value=date(2026, 11, 28))
    def test_before_due_reminder_includes_next_months_rent(self, _):
        # Paid up for November, so the old balance is 0 but December is coming.
        room = make_room(rent="5000")
        tenant = make_tenant(room, move_in=date(2026, 11, 1))
        pay(tenant, 5000)

        output = self.run_command("2026-11-28")

        self.assertIn("KES 5,000", output)
        self.assertIn("would send 1", output)

    @patch("django.utils.timezone.localdate", return_value=date(2026, 11, 28))
    def test_arrears_are_added_to_next_months_rent(self, _):
        room = make_room(rent="5000")
        make_tenant(room, move_in=date(2026, 11, 1))  # owes November

        output = self.run_command("2026-11-28")

        self.assertIn("KES 10,000", output)

    @patch("django.utils.timezone.localdate", return_value=date(2026, 12, 1))
    def test_on_due_reminder_uses_current_balance(self, _):
        room = make_room(rent="5000")
        make_tenant(room, move_in=date(2026, 11, 1))  # owes Nov + Dec

        output = self.run_command("2026-12-01")

        self.assertIn("KES 10,000", output)
        self.assertIn("is due today", output)

    @patch("django.utils.timezone.localdate", return_value=date(2026, 11, 28))
    def test_tenant_with_invalid_phone_is_skipped(self, _):
        room = make_room(rent="5000")
        tenant = make_tenant(room, move_in=date(2026, 11, 1))
        Tenant.objects.filter(pk=tenant.pk).update(phone="12345")

        output = self.run_command("2026-11-28")

        self.assertIn("would send 0", output)

    def test_no_reminder_on_other_days(self):
        output = self.run_command("2026-11-15")
        self.assertIn("no reminders scheduled", output)


# ---------- Tenant move-out ----------

@patch("django.utils.timezone.localdate", return_value=TODAY)
class MoveOutTests(TestCase):
    def setUp(self):
        self.room = make_room(rent="5000", capacity=1)

    def test_rent_stops_after_move_out_month(self, _):
        # Lived here August and September only.
        tenant = make_tenant(self.room, move_in=date(2026, 8, 1))
        tenant.move_out_date = date(2026, 9, 15)
        tenant.save()
        self.assertEqual(tenant.months_billed(), 2)
        self.assertEqual(tenant.balance(), Decimal("10000"))

    def test_unpaid_balance_is_kept_after_move_out(self, _):
        tenant = make_tenant(self.room, move_in=date(2026, 8, 1))
        tenant.move_out_date = date(2026, 9, 15)
        tenant.save()
        pay(tenant, 4000)
        self.assertEqual(tenant.balance(), Decimal("6000"))

    def test_moved_out_tenant_frees_the_room(self, _):
        old = make_tenant(self.room, move_in=date(2026, 8, 1))
        old.move_out_date = date(2026, 10, 31)
        old.save()
        form = TenantForm({
            "full_name": "New Tenant", "phone": "0722000111",
            "id_number": "99999999", "room": self.room.pk,
            "move_in_date": "2026-11-01",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_move_out_button_sets_the_date(self, _):
        from django.contrib.auth import get_user_model
        admin = get_user_model().objects.create_user(
            "admin1", password="pass12345", is_staff=True
        )
        tenant = make_tenant(self.room)
        self.client.force_login(admin)

        response = self.client.post(f"/tenants/{tenant.id}/move-out/")

        self.assertEqual(response.status_code, 302)
        tenant.refresh_from_db()
        self.assertEqual(tenant.move_out_date, TODAY)

    def test_move_out_needs_post(self, _):
        from django.contrib.auth import get_user_model
        admin = get_user_model().objects.create_user(
            "admin2", password="pass12345", is_staff=True
        )
        tenant = make_tenant(self.room)
        self.client.force_login(admin)

        response = self.client.get(f"/tenants/{tenant.id}/move-out/")

        self.assertEqual(response.status_code, 405)
        tenant.refresh_from_db()
        self.assertIsNone(tenant.move_out_date)

    def test_reminders_skip_moved_out_tenants(self, _):
        tenant = make_tenant(self.room, move_in=date(2026, 8, 1))
        tenant.move_out_date = date(2026, 9, 15)
        tenant.save()
        with patch("django.utils.timezone.localdate", return_value=date(2026, 11, 28)):
            out = StringIO()
            call_command("send_rent_reminders", dry_run=True, date="2026-11-28",
                         stdout=out, stderr=StringIO())
        self.assertIn("would send 0", out.getvalue())


# Delete and clear

class DeleteTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.User = get_user_model()
        self.admin = self.User.objects.create_user(
            "boss", password="pass12345", is_staff=True
        )
        self.client.force_login(self.admin)
        self.room = make_room(capacity=2)

    def test_empty_room_can_be_deleted(self):
        response = self.client.post(f"/rooms/{self.room.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Room.objects.filter(pk=self.room.pk).exists())

    def test_room_with_tenants_is_not_deleted(self):
        make_tenant(self.room)
        self.client.post(f"/rooms/{self.room.id}/delete/")
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())

    def test_room_with_only_past_tenants_is_not_deleted(self):
        tenant = make_tenant(self.room)
        tenant.move_out_date = date(2026, 9, 30)
        tenant.save()
        self.client.post(f"/rooms/{self.room.id}/delete/")
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())

    def test_deleting_a_tenant_removes_their_payments(self):
        tenant = make_tenant(self.room)
        pay(tenant, 5000)
        self.client.post(f"/tenants/{tenant.id}/delete/")
        self.assertFalse(Tenant.objects.filter(pk=tenant.pk).exists())
        self.assertEqual(Payment.objects.count(), 0)

    def test_deleting_a_tenant_removes_their_login_but_not_admins(self):
        tenant = make_tenant(self.room)
        login = self.User.objects.create_user("anna", password="pass12345")
        tenant.user = login
        tenant.save()
        self.client.post(f"/tenants/{tenant.id}/delete/")
        self.assertFalse(self.User.objects.filter(username="anna").exists())
        self.assertTrue(self.User.objects.filter(username="boss").exists())

    def test_payment_can_be_deleted(self):
        tenant = make_tenant(self.room)
        payment = pay(tenant, 5000)
        self.client.post(f"/payments/{payment.id}/delete/")
        self.assertEqual(Payment.objects.count(), 0)

    def test_clear_resolved_keeps_open_complaints(self):
        from .models import Complaint
        tenant = make_tenant(self.room)
        Complaint.objects.create(tenant=tenant, description="Fixed", status="Resolved")
        Complaint.objects.create(tenant=tenant, description="Leak", status="Open")
        self.client.post("/complaints/clear-resolved/")
        self.assertEqual(Complaint.objects.count(), 1)
        self.assertEqual(Complaint.objects.first().status, "Open")

    def test_delete_needs_post(self):
        response = self.client.get(f"/rooms/{self.room.id}/delete/")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())

    def test_tenants_cannot_delete_anything(self):
        tenant = make_tenant(self.room)
        login = self.User.objects.create_user("anna", password="pass12345")
        tenant.user = login
        tenant.save()
        self.client.force_login(login)
        self.client.post(f"/tenants/{tenant.id}/delete/")
        self.assertTrue(Tenant.objects.filter(pk=tenant.pk).exists())

    def test_pages_with_delete_buttons_load(self):
        from .models import Complaint
        tenant = make_tenant(self.room)
        pay(tenant, 1000)
        Complaint.objects.create(tenant=tenant, description="Leak", status="Open")
        for url in ["/", "/payments/", "/complaints/", "/balances/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
        self.assertContains(self.client.get("/"), "/rooms/")
        self.assertContains(self.client.get("/payments/"), "/delete/")

        

# Reports

@patch("django.utils.timezone.localdate", return_value=TODAY)
class ReportTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.User = get_user_model()
        admin = self.User.objects.create_user("boss", password="pass12345", is_staff=True)
        self.client.force_login(admin)

        self.room = make_room(rent="5000", capacity=2)
        # Anna owes 5,000 (two months billed, one paid).
        self.anna = make_tenant(self.room, name="Anna Wanjiku")
        pay(self.anna, 5000)
        # Brian is paid up.
        self.brian = make_tenant(
            self.room, move_in=date(2026, 11, 1), name="Brian Otieno",
            phone="0722000111", id_number="22222222",
        )
        pay(self.brian, 5000)

    def test_every_report_page_loads(self, _):
        for slug in ["rent-per-month", "arrears", "occupancy", "payments", "complaints"]:
            response = self.client.get(f"/reports/{slug}/")
            self.assertEqual(response.status_code, 200, slug)
        self.assertEqual(self.client.get("/reports/").status_code, 200)

    def test_unknown_report_is_404(self, _):
        self.assertEqual(self.client.get("/reports/nonsense/").status_code, 404)

    def test_arrears_lists_only_tenants_who_owe(self, _):
        response = self.client.get("/reports/arrears/")
        self.assertContains(response, "Anna Wanjiku")
        self.assertNotContains(response, "Brian Otieno")

    def test_arrears_csv_download(self, _):
        response = self.client.get("/reports/arrears/?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        text = response.content.decode("utf-8-sig")
        self.assertIn("Tenant,Phone,Room", text)
        self.assertIn("Anna Wanjiku", text)
        self.assertIn("5,000.00", text)
        self.assertNotIn("Brian Otieno", text)

    def test_every_report_downloads_as_a_real_pdf(self, _):
        for slug in ["rent-per-month", "arrears", "occupancy", "payments", "complaints"]:
            response = self.client.get(f"/reports/{slug}/?format=pdf")
            self.assertEqual(response.status_code, 200, slug)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(response.content.startswith(b"%PDF"), slug)

    def test_occupancy_report_counts_beds(self, _):
        response = self.client.get("/reports/occupancy/")
        self.assertContains(response, "2 of 2 (100%)")

    def test_moved_out_tenants_do_not_count_as_occupied(self, _):
        self.brian.move_out_date = date(2026, 11, 5)
        self.brian.save()
        response = self.client.get("/reports/occupancy/")
        self.assertContains(response, "1 of 2 (50%)")

    def test_payments_report_total(self, _):
        response = self.client.get("/reports/payments/")
        self.assertContains(response, "10,000.00")

    def test_payments_date_range_filters_out_everything(self, _):
        response = self.client.get("/reports/payments/?from=2000-01-01&to=2000-01-31")
        self.assertContains(response, "No data for this report")

    def test_invalid_date_is_ignored_with_a_message(self, _):
        response = self.client.get("/reports/payments/?from=not-a-date")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a valid date")

    def test_rent_per_month_groups_payments(self, _):
        response = self.client.get("/reports/rent-per-month/")
        self.assertContains(response, "10,000.00")

    def test_complaints_report_filters_by_status(self, _):
        from .models import Complaint
        Complaint.objects.create(tenant=self.anna, description="Broken tap", status="Open")
        Complaint.objects.create(tenant=self.anna, description="Old lock", status="Resolved")
        response = self.client.get("/reports/complaints/?status=open")
        self.assertContains(response, "Broken tap")
        self.assertNotContains(response, "Old lock")

    def test_csv_blocks_spreadsheet_formulas(self, _):
        from .models import Complaint
        Complaint.objects.create(
            tenant=self.anna, description="=HYPERLINK(\"http://x\")", status="Open"
        )
        text = self.client.get("/reports/complaints/?format=csv").content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)

    def test_tenants_cannot_open_reports(self, _):
        login = self.User.objects.create_user("anna", password="pass12345")
        self.anna.user = login
        self.anna.save()
        self.client.force_login(login)
        response = self.client.get("/reports/arrears/")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b"Anna", self.client.get("/reports/arrears/?format=csv").content)
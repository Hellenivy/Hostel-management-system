from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from hostel.models import RentReminder, Tenant
from hostel.mpesa import format_phone_number
from hostel.sms import send_sms


def reminder_for(today):
    """Return (kind, period, due_date) if a reminder goes out today, else None."""
    due_day = settings.RENT_DUE_DAY

    if not 1 <= due_day <= 28:
        raise CommandError("RENT_DUE_DAY must be between 1 and 28.")

    if today.day == due_day:
        return RentReminder.ON_DUE, today.replace(day=1), today

    upcoming = today + timedelta(days=settings.RENT_REMINDER_DAYS_BEFORE)
    if upcoming.day == due_day:
        return RentReminder.BEFORE_DUE, upcoming.replace(day=1), upcoming

    return None


def build_message(tenant, balance, due_date, kind):
    first_name = tenant.full_name.split()[0]
    when = "today" if kind == RentReminder.ON_DUE else f"on {due_date:%d %b}"
    return (
        f"Hi {first_name}, your rent balance of KES {balance:,.0f} "
        f"for room {tenant.room.room_number} is due {when}. "
        f"Pay via M-Pesa Paybill {settings.MPESA_SHORTCODE}, "
        f"account TENANT-{tenant.id}. Thank you - Smart Hostel"
    )


class Command(BaseCommand):
    help = "Send SMS rent reminders to tenants with a balance. Run once a day."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show who would be messaged without sending or recording anything.",
        )
        parser.add_argument(
            "--date",
            help="Pretend today is this date (YYYY-MM-DD). Useful for testing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        try:
            today = date.fromisoformat(options["date"]) if options["date"] else date.today()
        except ValueError:
            raise CommandError("--date must be in YYYY-MM-DD format.")

        schedule = reminder_for(today)
        if schedule is None:
            self.stdout.write(f"{today}: no reminders scheduled today.")
            return

        kind, period, due_date = schedule

        if not dry_run and not settings.AT_API_KEY:
            raise CommandError("AT_API_KEY is not set in .env. Use --dry-run to preview.")

        sent = skipped = failed = 0

        for tenant in Tenant.objects.filter(room__isnull=False).select_related("room"):
            balance = tenant.balance()

            # A "before due" reminder goes out in the month before the rent is
            # billed, so the coming month's rent is not in the balance yet.
            if (
                kind == RentReminder.BEFORE_DUE
                and due_date.month != today.month
                and tenant.move_in_date <= due_date
            ):
                balance += tenant.room.rent_amount

            if balance <= 0:
                continue

            already = RentReminder.objects.filter(
                tenant=tenant, kind=kind, period=period, status="Sent"
            ).exists()
            if already:
                skipped += 1
                continue

            phone = format_phone_number(tenant.phone)
            if phone is None:
                self.stderr.write(f"  {tenant.full_name}: invalid phone '{tenant.phone}', skipped")
                failed += 1
                continue

            message = build_message(tenant, balance, due_date, kind)

            if dry_run:
                self.stdout.write(f"  would text {phone}: {message}")
                sent += 1
                continue

            try:
                ok, detail = send_sms(phone, message)
            except Exception as error:
                ok, detail = False, str(error)

            RentReminder.objects.update_or_create(
                tenant=tenant,
                kind=kind,
                period=period,
                defaults={
                    "amount_due": balance,
                    "status": "Sent" if ok else "Failed",
                    "provider_response": detail[:255],
                },
            )

            if ok:
                sent += 1
                self.stdout.write(f"  sent to {tenant.full_name} ({phone})")
            else:
                failed += 1
                self.stderr.write(f"  failed for {tenant.full_name}: {detail}")

        label = "would send" if dry_run else "sent"
        self.stdout.write(
            f"{today} [{kind}, due {due_date}]: {label} {sent}, "
            f"already reminded {skipped}, failed {failed}."
        )
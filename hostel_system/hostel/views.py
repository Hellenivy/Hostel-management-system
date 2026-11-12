import hmac
import json
import logging
from datetime import timedelta
from django.db import transaction
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm

from .decorators import staff_required
from .models import Room, Tenant, Payment, Complaint, MpesaTransaction
from .forms import (
    PaymentForm, RoomForm, TenantForm, ComplaintForm,
    TenantComplaintForm, AdminUserForm, TenantAccountForm,
)
from .mpesa import initiate_stk_push, query_stk_push, format_phone_number

User = get_user_model()
logger = logging.getLogger(__name__)

# An STK prompt expires on the phone after about a minute; pending requests
# older than this no longer hold back the tenant's balance.
STK_PENDING_TIMEOUT = timedelta(minutes=3)


def rent_summary(tenant):
    """Rent is billed monthly, starting from the tenant's move-in month."""
    monthly_rent = tenant.room.rent_amount if tenant.room else Decimal("0.00")
    months_billed = tenant.months_billed()

    rent_due = monthly_rent * months_billed

    total_paid = sum(
        Payment.objects.filter(tenant=tenant).values_list("amount", flat=True),
        Decimal("0.00"),
    )

    return {
        "monthly_rent": monthly_rent,
        "months_billed": months_billed,
        "rent_due": rent_due,
        "total_paid": total_paid,
        "balance": rent_due - total_paid,
    }


@staff_required
def dashboard(request):
    rooms = Room.objects.all()
    room_list = []

    for room in rooms:
        tenants = Tenant.objects.filter(room=room, move_out_date__isnull=True)
        count = tenants.count()

        if count == 0:
            status = "Vacant"
        elif count >= room.capacity:
            status = "Full"
        else:
            status = "Partly occupied"

        if room.capacity > 0:
            occupancy_pct = min(100, count * 100 // room.capacity)
        else:
            occupancy_pct = 0

        room_list.append({
            "room": room,
            "tenants": tenants,
            "count": count,
            "status": status,
            "occupancy_pct": occupancy_pct,
        })

    total_beds = sum(item["room"].capacity for item in room_list)
    occupied_beds = sum(item["count"] for item in room_list)

    stats = {
        "rooms": len(room_list),
        "vacant_rooms": sum(1 for item in room_list if item["status"] == "Vacant"),
        "total_beds": total_beds,
        "occupied_beds": occupied_beds,
        "occupancy_pct": occupied_beds * 100 // total_beds if total_beds else 0,
        "open_complaints": Complaint.objects.filter(status="Open").count(),
    }

    return render(
        request,
        "hostel/dashboard.html",
        {"room_list": room_list, "stats": stats},
    )


@staff_required
def payments(request):
    all_payments = Payment.objects.all().order_by('-date_paid')
    return render(request, "hostel/payments.html", {"payments": all_payments})



@staff_required
def add_payment(request):
    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('payments')
    else:
        form = PaymentForm()
    return render(request, "hostel/add_payment.html", {"form": form})


@staff_required
def add_room(request):
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = RoomForm()
    return render(request, "hostel/add_room.html", {"form": form})

@staff_required
def add_tenant(request):
    if request.method == "POST":
        form = TenantForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = TenantForm()
    return render(request, "hostel/add_tenant.html", {"form": form})


@staff_required
def edit_tenant(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == "POST":
        form = TenantForm(request.POST, instance=tenant)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = TenantForm(instance=tenant)
    return render(request, "hostel/edit_tenant.html", {"form": form, "tenant": tenant})


@staff_required
@require_POST
def move_out_tenant(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)

    if tenant.move_out_date:
        messages.error(request, f"{tenant.full_name} has already moved out.")
    else:
        tenant.move_out_date = timezone.localdate()
        tenant.save(update_fields=["move_out_date"])
        messages.success(
            request,
            f"{tenant.full_name} has been marked as moved out. "
            "Their payment history and any balance are kept.",
        )
    return redirect("dashboard")


@staff_required
def balances(request):
    tenants = Tenant.objects.select_related("room")
    balance_list = []

    for tenant in tenants:
        summary = rent_summary(tenant)
        balance = summary["balance"]

        if balance < 0:
            status = "Overpaid"
        elif balance == 0:
            status = "Paid up"
        else:
            status = "Owes"

        balance_list.append({
            "tenant": tenant,
            "rent_due": summary["rent_due"],
            "total_paid": summary["total_paid"],
            "balance": balance,
            "status": status,
        })

    stats = {
        "rent_due": sum(item["rent_due"] for item in balance_list),
        "collected": sum(item["total_paid"] for item in balance_list),
        "outstanding": sum(
            item["balance"] for item in balance_list if item["balance"] > 0
        ),
        "owing_count": sum(1 for item in balance_list if item["balance"] > 0),
    }

    return render(
        request,
        "hostel/balances.html",
        {"balance_list": balance_list, "stats": stats}
    )


@login_required
def complaints(request):
    # Admins see every complaint; a tenant sees only their own.
    if request.user.is_staff:
        visible = Complaint.objects.all()
    else:
        visible = Complaint.objects.filter(tenant__user=request.user)
    return render(
        request,
        "hostel/complaints.html",
        {"complaints": visible.select_related("tenant__room").order_by('-created_at')},
    )


@login_required
def add_complaint(request):
    tenant = None
    form_class = ComplaintForm

    if not request.user.is_staff:
        tenant = _own_tenant(request)
        if tenant is None:
            messages.error(request, "Your login is not linked to a tenant record yet.")
            return redirect('my_account')
        # Tenants can't pick who the complaint is for.
        form_class = TenantComplaintForm

    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            complaint = form.save(commit=False)
            if tenant is not None:
                complaint.tenant = tenant
            complaint.save()
            messages.success(request, "Complaint submitted.")
            return redirect('complaints')
    else:
        form = form_class()
    return render(request, "hostel/add_complaint.html", {"form": form})



@staff_required
def resolve_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)
    if request.method == "POST":
        complaint.status = "Resolved"
        complaint.save()
    return redirect('complaints')



def _valid_callback_token(token):
    expected = settings.MPESA_CALLBACK_TOKEN

    if not expected:
        return False

    return hmac.compare_digest(token.encode(), expected.encode())


@csrf_exempt
def mpesa_callback(request, token):
    # Reject anything that does not carry the secret callback token. A 404
    # avoids confirming to a prober that the endpoint exists.
    if not _valid_callback_token(token):
        logger.warning("M-Pesa callback: invalid token")
        raise Http404

    if request.method != "POST":
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "POST required"},
            status=405,
        )

    # Read and validate the callback.
    try:
        data = json.loads(request.body.decode("utf-8"))
        callback = data["Body"]["stkCallback"]

        checkout_id = callback.get("CheckoutRequestID")
        result_code = callback.get("ResultCode")

        if not checkout_id or result_code is None:
            return JsonResponse(
                {"ResultCode": 1, "ResultDesc": "Missing callback details"},
                status=400,
            )

    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError):
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "Invalid callback data"},
            status=400,
        )

    # Find the transaction created when the STK Push was initiated.
    mpesa_transaction = MpesaTransaction.objects.filter(
        checkout_request_id=checkout_id
    ).first()

    if mpesa_transaction is None:
        logger.warning("M-Pesa callback: transaction not found")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Received"}
        )

    # Handle unsuccessful or cancelled payments.
    if str(result_code) != "0":
        with transaction.atomic():
            locked_transaction = (
                MpesaTransaction.objects.select_for_update()
                .filter(checkout_request_id=checkout_id)
                .first()
            )

            if (
                locked_transaction is not None
                and locked_transaction.status == "Pending"
            ):
                locked_transaction.status = "Failed"
                locked_transaction.result_code = str(result_code)
                locked_transaction.save(
                    update_fields=["status", "result_code"]
                )

        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Received"}
        )

    # Extract the receipt and amount from the successful callback.
    metadata = callback.get("CallbackMetadata", {}).get("Item", [])

    values = {
        item.get("Name"): item.get("Value")
        for item in metadata
        if isinstance(item, dict) and "Name" in item
    }

    receipt = values.get("MpesaReceiptNumber")
    callback_amount = values.get("Amount")

    if (
        not isinstance(receipt, str)
        or not receipt.isalnum()
        or len(receipt) > 20
        or callback_amount is None
    ):
        logger.warning("M-Pesa callback: receipt or amount missing or invalid")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Verification pending"}
        )

    try:
        received_amount = Decimal(str(callback_amount))
    except (ValueError, TypeError, ArithmeticError):
        logger.warning("M-Pesa callback: invalid amount")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Verification pending"}
        )

    # Reject payments whose amount differs from the recorded transaction.
    if received_amount != mpesa_transaction.amount:
        logger.warning("M-Pesa callback: amount mismatch")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Verification pending"}
        )

    # Save the payment safely and prevent duplicate receipts.
    with transaction.atomic():
        locked_transaction = (
            MpesaTransaction.objects.select_for_update()
            .filter(checkout_request_id=checkout_id)
            .first()
        )

        if locked_transaction is None:
            return JsonResponse(
                {"ResultCode": 0, "ResultDesc": "Received"}
            )

        # Do not process a transaction that has already been handled.
        if locked_transaction.status in ("Success", "Failed"):
            return JsonResponse(
                {"ResultCode": 0, "ResultDesc": "Already processed"}
            )

        existing_payment = Payment.objects.filter(
            mpesa_code=receipt
        ).first()

        if existing_payment:
            # A receipt cannot belong to a different tenant or amount.
            if (
                existing_payment.tenant_id != locked_transaction.tenant_id
                or existing_payment.amount != locked_transaction.amount
            ):
                logger.warning("M-Pesa callback: receipt conflict")
                return JsonResponse(
                    {"ResultCode": 0, "ResultDesc": "Receipt conflict"}
                )
        else:
            Payment.objects.create(
                tenant=locked_transaction.tenant,
                amount=locked_transaction.amount,
                mpesa_code=receipt,
            )

        locked_transaction.mpesa_receipt_number = receipt
        locked_transaction.status = "Success"
        locked_transaction.result_code = str(result_code)
        locked_transaction.save(
            update_fields=[
                "status",
                "result_code",
                "mpesa_receipt_number",
            ]
        )

    logger.info("M-Pesa callback processed")

    return JsonResponse(
        {"ResultCode": 0, "ResultDesc": "Accepted"}
    )


@staff_required
@require_POST
def request_mpesa_payment(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)

    try:
        amount = Decimal(str(request.POST.get("amount", "")))
    except (InvalidOperation, ValueError):
        messages.error(request, "Please enter a valid payment amount.")
        return redirect("balances")

    if not amount.is_finite() or amount <= 0:
        messages.error(request, "The amount must be greater than zero.")
        return redirect("balances")

    if amount != amount.to_integral_value():
        messages.error(
            request,
            "M-Pesa payments must be entered in whole Kenyan shillings.",
        )
        return redirect("balances")

    phone = format_phone_number(tenant.phone)

    if phone is None:
        messages.error(
            request,
            f"'{tenant.phone}' is not a valid Safaricom number. "
            "Use the format 07XXXXXXXX or 2547XXXXXXXX.",
        )
        return redirect("balances")

    summary = rent_summary(tenant)
    rent_due = summary["rent_due"]
    total_paid = summary["total_paid"]

    pending_total = sum(
        MpesaTransaction.objects.filter(
            tenant=tenant,
            status="Pending",
            created_at__gte=timezone.now() - STK_PENDING_TIMEOUT,
        ).values_list("amount", flat=True),
        Decimal("0.00"),
    )

    balance = rent_due - total_paid - pending_total

    if balance <= 0 or amount > balance:
        messages.error(
            request,
            "The amount exceeds the tenant's available rent balance.",
        )
        return redirect("balances")

    mpesa_transaction = MpesaTransaction.objects.create(
        tenant=tenant,
        amount=amount,
        status="Pending",
    )

    try:
        result = initiate_stk_push(
            phone=phone,
            amount=amount,
            tenant_id=tenant.id,
        )

        checkout_id = result.get("CheckoutRequestID")
        merchant_id = result.get("MerchantRequestID")

        if result.get("ResponseCode") != "0" or not checkout_id:
            mpesa_transaction.status = "Failed"
            mpesa_transaction.save(update_fields=["status"])

            messages.error(
                request,
                result.get("errorMessage")
                or result.get("ResponseDescription")
                or "Safaricom did not accept the payment request.",
            )
            return redirect("balances")

        mpesa_transaction.checkout_request_id = checkout_id
        mpesa_transaction.merchant_request_id = merchant_id or ""

        mpesa_transaction.save(
            update_fields=[
                "checkout_request_id",
                "merchant_request_id",
            ]
        )

        messages.success(
            request,
            "M-Pesa request sent. Check the tenant's phone to complete payment.",
        )

    except Exception as error:
        logger.exception("M-Pesa STK push request failed: %s", error)

        mpesa_transaction.status = "Failed"
        mpesa_transaction.save(update_fields=["status"])

        messages.error(
            request,
            "The M-Pesa request could not be completed. "
            "Check the server logs before retrying.",
        )

    return redirect("balances")

# Delete and clear (admin only)

@staff_required
@require_POST
def delete_room(request, room_id):
    room = get_object_or_404(Room, id=room_id)

    # Past tenants still point at their old roomand deleting it would wipe the room from their rent history.
    if Tenant.objects.filter(room=room).exists():
        messages.error(
            request,
            f"Room {room.room_number} still has tenants (current or past). "
            "Move them to another room or delete them first.",
        )
    else:
        number = room.room_number
        room.delete()
        messages.success(request, f"Room {number} deleted.")
    return redirect("dashboard")


@staff_required
@require_POST
def delete_tenant(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    name = tenant.full_name
    payment_count = tenant.payment_set.count()
    login = tenant.user

    tenant.delete()

    #Tenant's login is useless without the tenant;never touch admin accounts.
    if login is not None and not login.is_staff:
        login.delete()

    messages.success(
        request,
        f"{name} deleted, with {payment_count} payment record(s) and all their complaints.",
    )
    if request.POST.get("next") == "balances":
        return redirect("balances")
    return redirect("dashboard")


@staff_required
@require_POST
def delete_payment(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    payment.delete()
    messages.success(request, "Payment deleted.")
    return redirect("payments")


@staff_required
@require_POST
def clear_resolved_complaints(request):
    deleted, _ = Complaint.objects.filter(status="Resolved").delete()
    messages.success(request, f"{deleted} resolved complaint(s) cleared.")
    return redirect("complaints")

# User management (admins only) 

@staff_required
def users(request):
    all_users = (
        User.objects.select_related("tenant_profile")
        .order_by("-is_staff", "username")
    )
    return render(request, "hostel/users.html", {"users": all_users})


@staff_required
def add_admin(request):
    if request.method == "POST":
        form = AdminUserForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Admin account '{user.username}' created.")
            return redirect("users")
    else:
        form = AdminUserForm()
    return render(request, "hostel/user_form.html", {
        "form": form,
        "title": "New admin",
        "subtitle": "Admins can manage rooms, tenants, payments and other users.",
        "submit_label": "Create admin",
    })


@staff_required
def add_tenant_account(request):
    if request.method == "POST":
        form = TenantAccountForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f"Login '{user.username}' created for {user.tenant_profile.full_name}.",
            )
            return redirect("users")
    else:
        form = TenantAccountForm(initial={"tenant": request.GET.get("tenant")})
    return render(request, "hostel/user_form.html", {
        "form": form,
        "title": "New tenant login",
        "subtitle": "The tenant will only see their own room, balance, payments and complaints.",
        "submit_label": "Create login",
    })


def _can_manage(actor, target):
    # A regular admin must not be able to take over a superuser's account.
    return actor.is_superuser or not target.is_superuser


@staff_required
def set_user_password(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user == request.user:
        return redirect("change_password")

    if not _can_manage(request.user, user):
        messages.error(request, "Only a superuser can reset a superuser's password.")
        return redirect("users")

    if request.method == "POST":
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Password for '{user.username}' has been reset.")
            return redirect("users")
    else:
        form = SetPasswordForm(user)
    return render(request, "hostel/user_form.html", {
        "form": form,
        "title": f"Reset password: {user.username}",
        "subtitle": "Set a new password and share it with the user securely. They can change it after logging in.",
        "submit_label": "Reset password",
    })


@staff_required
@require_POST
def toggle_user_active(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user == request.user:
        messages.error(request, "You can't deactivate your own account.")
        return redirect("users")

    if not _can_manage(request.user, user):
        messages.error(request, "Only a superuser can deactivate a superuser.")
        return redirect("users")

    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    state = "reactivated" if user.is_active else "deactivated"
    messages.success(request, f"Account '{user.username}' {state}.")
    return redirect("users")


# Tenant portal 

def _own_tenant(request):
    # The only tenant record a tenant user may ever see.
    return Tenant.objects.filter(user=request.user).select_related("room").first()


@login_required
def my_account(request):
    if request.user.is_staff:
        return redirect("dashboard")

    tenant = _own_tenant(request)
    if tenant is None:
 #student who is not a tenant yet:send them to book a room.
        return redirect("book_rooms")
    return render(request, "hostel/my_account.html", {
        "tenant": tenant,
        "balance": tenant.balance(),
        "payments": tenant.payment_set.order_by("-date_paid"),
        "open_complaints": tenant.complaint_set.filter(status="Open").count(),
        "paybill": settings.MPESA_SHORTCODE,
    })
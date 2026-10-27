import json
from django.db import transaction
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Room, Tenant, Payment, Complaint, MpesaTransaction
from .forms import PaymentForm, RoomForm, TenantForm, ComplaintForm
from .mpesa import initiate_stk_push,query_stk_push

@login_required
def dashboard(request):
    rooms = Room.objects.all()
    room_list = []

    for room in rooms:
        tenants = Tenant.objects.filter(room=room)
        count = tenants.count()

        if count == 0:
            status = "Vacant"
        elif count >= room.capacity:
            status = "Full"
        else:
            status = "Partly occupied"

        room_list.append({
            "room": room,
            "tenants": tenants,
            "count": count,
            "status": status,
        })

    return render(request, "hostel/dashboard.html", {"room_list": room_list})


@login_required
def payments(request):
    all_payments = Payment.objects.all().order_by('-date_paid')
    return render(request, "hostel/payments.html", {"payments": all_payments})



@login_required
def add_payment(request):
    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('payments')
    else:
        form = PaymentForm()
    return render(request, "hostel/add_payment.html", {"form": form})


@login_required
def add_room(request):
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = RoomForm()
    return render(request, "hostel/add_room.html", {"form": form})

@login_required
def add_tenant(request):
    if request.method == "POST":
        form = TenantForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = TenantForm()
    return render(request, "hostel/add_tenant.html", {"form": form})



@login_required
def balances(request):
    tenants = Tenant.objects.all()
    balance_list = []

    for tenant in tenants:
        if tenant.room:
            rent_due = tenant.room.rent_amount
        else:
            rent_due = 0

        total_paid = 0
        for p in Payment.objects.filter(tenant=tenant):
            total_paid = total_paid + p.amount

        balance = rent_due - total_paid

        if balance < 0:
            status = "Overpaid"
        elif balance == 0:
            status = "Paid up"
        else:
            status = "Owes"

        balance_list.append({
            "tenant": tenant,
            "rent_due": rent_due,
            "total_paid": total_paid,
            "balance": balance,
            "status": status,
        })

    return render(
        request,
        "hostel/balances.html",
        {"balance_list": balance_list}
    )


@login_required
def complaints(request):
    all_complaints = Complaint.objects.all().order_by('-created_at')
    return render(request, "hostel/complaints.html", {"complaints": all_complaints})


@login_required
def add_complaint(request):
    if request.method == "POST":
        form = ComplaintForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('complaints')
    else:
        form = ComplaintForm()
    return render(request, "hostel/add_complaint.html", {"form": form})



@login_required
def resolve_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)
    if request.method == "POST":
        complaint.status = "Resolved"
        complaint.save()
    return redirect('complaints')



@csrf_exempt
def mpesa_callback(request):
    if request.method != "POST":
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "POST required"},
            status=405,
        )

    # Read and validate the callback.
    try:
        data = json.loads(request.body.decode("utf-8"))
        callback = data["Body"]["stkCallback"]
        print("M-PESA CALLBACK DATA:", callback)

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
        print("M-Pesa callback: transaction not found")
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

    if not receipt or callback_amount is None:
        print("M-Pesa callback: receipt or amount missing")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Verification pending"}
        )

    try:
        received_amount = Decimal(str(callback_amount))
    except (ValueError, TypeError, ArithmeticError):
        print("M-Pesa callback: invalid amount")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Verification pending"}
        )

    # Reject payments whose amount differs from the recorded transaction.
    if received_amount != mpesa_transaction.amount:
        print("M-Pesa callback: amount mismatch")
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
                print("M-Pesa callback: receipt conflict")
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

    print("M-Pesa callback processed")

    return JsonResponse(
        {"ResultCode": 0, "ResultDesc": "Accepted"}
    )


@login_required
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

    rent_due = (
        tenant.room.rent_amount
        if tenant.room
        else Decimal("0.00")
    )

    total_paid = sum(
        Payment.objects.filter(tenant=tenant).values_list(
            "amount", flat=True
        ),
        Decimal("0.00"),
    )

    pending_total = sum(
        MpesaTransaction.objects.filter(
            tenant=tenant,
            status="Pending",
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
            phone=tenant.phone,
            amount=amount,
            tenant_id=tenant.id,
        )

        # Diagnostic: display Safaricom's initial response.
        print("M-PESA INITIAL RESPONSE:", result)

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
        # Log exception for troubleshooting.
        print("M-PESA REQUEST ERROR:", str(error))

        mpesa_transaction.status = "Failed"
        mpesa_transaction.save(update_fields=["status"])

        messages.error(
            request,
            "The M-Pesa request could not be completed. "
            "Check the server logs before retrying.",
        )

    return redirect("balances")




# Create your views here.
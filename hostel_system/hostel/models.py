from django.db import models


class Room(models.Model):
    room_number = models.CharField(max_length=10, unique=True)
    rent_amount = models.DecimalField(max_digits=8, decimal_places=2)
    capacity = models.IntegerField(default=1)

    def __str__(self):
        return self.room_number


class Tenant(models.Model):
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    id_number = models.CharField(max_length=20)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True)
    move_in_date = models.DateField()

    def __str__(self):
        return self.full_name


class Payment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    mpesa_code = models.CharField(max_length=20, blank=True, unique=True, null=True)
    date_paid = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tenant.full_name} - {self.amount}"  

    

class MpesaTransaction(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    checkout_request_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    merchant_request_id = models.CharField(
        max_length=100,
        blank=True,
    )
    status = models.CharField(max_length=20, default="Pending")
    result_code = models.CharField(max_length=20, blank=True)
    mpesa_receipt_number = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tenant.full_name} - {self.amount} - {self.status}"

class RentReminder(models.Model):
    BEFORE_DUE = "before_due"
    ON_DUE = "on_due"
    KIND_CHOICES = [
        (BEFORE_DUE, "Before due date"),
        (ON_DUE, "On due date"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    # First day of the rent month this reminder is for.
    period = models.DateField()
    amount_due = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=20, default="Pending")
    provider_response = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One reminder of each kind per tenant per month.
        unique_together = ("tenant", "kind", "period")

    def __str__(self):
        return f"{self.tenant.full_name} - {self.kind} - {self.period:%b %Y} - {self.status}"


class Complaint(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    description = models.TextField()
    status = models.CharField(max_length=20, default='Open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tenant.full_name} - {self.status}"  
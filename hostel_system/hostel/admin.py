from django.contrib import admin
from .models import Room, Tenant,Payment,Complaint,RentReminder,MpesaTransaction

admin.site.register(Room)
admin.site.register(Tenant)
admin.site.register(Payment)
admin.site.register(Complaint)


@admin.register(RentReminder)
class RentReminderAdmin(admin.ModelAdmin):
    list_display = ("tenant", "kind", "period", "amount_due", "status", "sent_at")
    list_filter = ("kind", "status", "period")


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "amount", "status", "mpesa_receipt_number", "created_at")
    list_filter = ("status",)

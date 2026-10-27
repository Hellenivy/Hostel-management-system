from django.contrib import admin
from .models import Room, Tenant,Payment,Complaint

admin.site.register(Room)
admin.site.register(Tenant)
admin.site.register(Payment)
admin.site.register(Complaint)

# Register your models here.

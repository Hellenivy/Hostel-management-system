from django import forms
from .models import Payment,Room,Tenant,Complaint


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['tenant', 'amount', 'mpesa_code']


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['room_number', 'rent_amount', 'capacity']   


class TenantForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ['full_name', 'phone', 'id_number', 'room', 'move_in_date']
        widgets = {
            'move_in_date': forms.DateInput(attrs={'type': 'date'}),
        }



class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ['tenant', 'description']        
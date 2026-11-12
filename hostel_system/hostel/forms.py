from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Booking,Payment,Room,Tenant,Complaint
from .mpesa import format_phone_number


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['full_name', 'phone', 'id_number', 'move_in_date']
        widgets = {
            'move_in_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if format_phone_number(phone) is None:
            raise forms.ValidationError(
                "Enter a valid Safaricom number,like 0712345678."
            )
        return phone
class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['tenant', 'amount', 'mpesa_code']

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= 0:
            raise forms.ValidationError("The amount must be greater than zero.")
        return amount

    def clean_mpesa_code(self):
        code = self.cleaned_data.get('mpesa_code')
        return code.strip().upper() if code else code


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

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if format_phone_number(phone) is None:
            raise forms.ValidationError(
                "Enter a valid Safaricom number, like 0712345678."
            )
        return phone

    def clean_id_number(self):
        id_number = self.cleaned_data.get('id_number', '').strip()
        duplicate = (
            Tenant.objects.filter(id_number__iexact=id_number)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if duplicate:
            raise forms.ValidationError(
                "A tenant with this ID number already exists."
            )
        return id_number

    def clean_room(self):
        room = self.cleaned_data.get('room')
        if room:
            current = (
                Tenant.objects.filter(room=room, move_out_date__isnull=True)
                .exclude(pk=self.instance.pk)
                .count()
            )
            if current >= room.capacity:
                raise forms.ValidationError("This room is already full.")
        return room


class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ['tenant', 'description']


class TenantComplaintForm(forms.ModelForm):
    # Tenants only describe the issue; the view attaches their own record.
    class Meta:
        model = Complaint
        fields = ['description']
        labels = {'description': 'What is the issue?'}


class AdminUserForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ('username', 'first_name', 'last_name', 'email')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        if commit:
            user.save()
        return user


class TenantAccountForm(UserCreationForm):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        help_text="Only tenants without a login are listed.",
    )

    class Meta(UserCreationForm.Meta):
        fields = ('tenant', 'username')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tenant'].queryset = Tenant.objects.filter(user__isnull=True).order_by('full_name')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = False
        if commit:
            user.save()
            tenant = self.cleaned_data['tenant']
            tenant.user = user
            tenant.save(update_fields=['user'])
        return user
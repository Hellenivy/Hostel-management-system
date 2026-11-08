from django import forms
from django.contrib.auth.forms import UserCreationForm
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
    def clean_room(self):
        room = self.cleaned_data.get('room')
        if room:
            current = Tenant.objects.filter(room=room).exclude(pk=self.instance.pk).count()
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
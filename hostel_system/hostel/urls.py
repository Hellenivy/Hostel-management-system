from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('payments/', views.payments, name='payments'),
    path('payments/add/', views.add_payment, name='add_payment'),
    path('rooms/add/', views.add_room, name='add_room'),
    path('tenants/add/', views.add_tenant, name='add_tenant'),
    path('balances/', views.balances, name='balances'),
    path('complaints/', views.complaints, name='complaints'),
    path('complaints/add/', views.add_complaint, name='add_complaint'),
    path('complaints/<int:complaint_id>/resolve/', views.resolve_complaint, name='resolve_complaint'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('mpesa/request/<int:tenant_id>/', views.request_mpesa_payment, name='request_mpesa_payment'),
]

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from . import reports,student_views,views
urlpatterns = [
    path(
        'account/password/',
        auth_views.PasswordChangeView.as_view(
            template_name='hostel/password_change.html',
            success_url=reverse_lazy('change_password_done'),
        ),
        name='change_password',
    ),
    path(
        'account/password/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='hostel/password_change_done.html',
        ),
        name='change_password_done',
    ),
    path('', views.dashboard, name='dashboard'),
    path('payments/', views.payments, name='payments'),
    path('payments/add/', views.add_payment, name='add_payment'),
    path('rooms/add/', views.add_room, name='add_room'),
    path('tenants/add/', views.add_tenant, name='add_tenant'),
    path('tenants/<int:tenant_id>/edit/', views.edit_tenant, name='edit_tenant'),
    path('tenants/<int:tenant_id>/move-out/', views.move_out_tenant, name='move_out_tenant'),
    path('rooms/<int:room_id>/delete/', views.delete_room, name='delete_room'),
    path('tenants/<int:tenant_id>/delete/', views.delete_tenant, name='delete_tenant'),
    path('payments/<int:payment_id>/delete/', views.delete_payment, name='delete_payment'),
    path('complaints/clear-resolved/', views.clear_resolved_complaints, name='clear_resolved_complaints'),
    path('register/', student_views.register, name='register'),
    path('book/', student_views.book_rooms, name='book_rooms'),
    path('book/<int:room_id>/', student_views.book_room_page, name='book_room'),
    path('reports/', reports.reports_index, name='reports'),
    path('reports/<slug:slug>/', reports.report_detail, name='report_detail'),
    path('balances/', views.balances, name='balances'),
    path('complaints/', views.complaints, name='complaints'),
    path('complaints/add/', views.add_complaint, name='add_complaint'),
    path('complaints/<int:complaint_id>/resolve/', views.resolve_complaint, name='resolve_complaint'),
    path('users/', views.users, name='users'),
    path('users/add-admin/', views.add_admin, name='add_admin'),
    path('users/add-tenant-login/', views.add_tenant_account, name='add_tenant_account'),
    path('users/<int:user_id>/toggle-active/', views.toggle_user_active, name='toggle_user_active'),
    path('users/<int:user_id>/set-password/', views.set_user_password, name='set_user_password'),
    path('my/', views.my_account, name='my_account'),
    path('mpesa/callback/<str:token>/', views.mpesa_callback, name='mpesa_callback'),
    path('mpesa/request/<int:tenant_id>/', views.request_mpesa_payment, name='request_mpesa_payment'),
]

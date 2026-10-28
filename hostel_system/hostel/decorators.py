from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def staff_required(view):
    """Allow only admins (staff users). Tenants are sent to their own page."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect("my_account")
        return view(request, *args, **kwargs)

    return login_required(wrapper)

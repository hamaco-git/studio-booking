from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "name", "role", "email", "is_active", "last_login")
    list_filter = ("role", "is_active")
    search_fields = ("username", "name", "email")
    ordering = ("role", "name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("기본 정보", {"fields": ("name", "email", "phone", "role")}),
        ("상태", {"fields": ("is_active", "must_change_password", "last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "name", "email", "role", "password1", "password2"),
        }),
    )
    readonly_fields = ("last_login", "date_joined")

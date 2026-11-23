from django.contrib import admin

from .models import AuditLog, Blackout, OpenSlot, Reservation, SlotTemplate


class CreatedByMixin:
    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, "created_by_id"):
            obj.created_by = request.user
        if hasattr(obj, "updated_by_id"):
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(OpenSlot)
class OpenSlotAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ("date", "studio", "label", "start_time", "end_time")
    list_filter = ("studio",)
    date_hierarchy = "date"


@admin.register(Blackout)
class BlackoutAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ("date", "studio", "start_time", "end_time", "reason")
    list_filter = ("studio",)
    date_hierarchy = "date"


@admin.register(Reservation)
class ReservationAdmin(CreatedByMixin, admin.ModelAdmin):
    list_display = ("date", "start_time", "end_time", "studio", "professor", "course", "status")
    list_filter = ("status", "studio")
    search_fields = ("professor__name", "course__name")
    date_hierarchy = "date"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target_table", "target_id", "summary")
    search_fields = ("summary", "user__name")
    list_filter = ("action", "target_table")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SlotTemplate)
class SlotTemplateAdmin(admin.ModelAdmin):
    list_display = ("label", "start_time", "end_time", "order", "is_active")

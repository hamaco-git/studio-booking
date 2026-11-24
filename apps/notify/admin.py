from django.contrib import admin

from .models import SmsLog


@admin.register(SmsLog)
class SmsLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "receiver", "reservation", "shoot_date", "mode", "status", "result_message"]
    list_filter = ["status", "kind", "mode"]
    search_fields = ["receiver", "text", "reservation__professor__name"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in SmsLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

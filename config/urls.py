from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "스튜디오 예약 시스템 관리"
admin.site.site_title = "스튜디오 예약 관리"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.booking.urls")),
]

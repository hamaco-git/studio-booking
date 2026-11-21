from django.urls import path

from . import views, views_professor

app_name = "booking"

urlpatterns = [
    path("calendar/", views.calendar, name="calendar"),
    path("api/events/", views.events, name="events"),
    path("slots/week/", views.week_slots, name="week_slots"),
    path("blackouts/", views.blackouts, name="blackouts"),
    path("blackouts/<int:pk>/delete/", views.blackout_delete, name="blackout_delete"),
    path("reservations/", views.reservations, name="reservations"),
    path("reservations/<int:pk>/", views.reservation_edit, name="reservation_edit"),
    path("reservations/<int:pk>/cancel/", views.reservation_cancel, name="reservation_cancel"),
    path("reservations/export/", views.reservations_export, name="reservations_export"),
    path("reservations/new/", views.reservation_new, name="reservation_new"),
    # 교수
    path("book/", views_professor.book, name="book"),
    path("book/reserve/", views_professor.reserve, name="reserve"),
    path("my/", views_professor.my_reservations, name="my_reservations"),
    path("my/<int:pk>/cancel/", views_professor.my_cancel, name="my_cancel"),
]

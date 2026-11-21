from django.urls import path

from . import views

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
]

"""교수 화면: 예약 달력, 예약 신청, 내 예약, 취소."""

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .models import OpenSlot, Reservation
from .permissions import professor_required


def _errors(e):
    return " ".join(e.messages)


@professor_required
def book(request):
    courses = list(services.professor_courses(request.user))
    cid = request.GET.get("course", "")
    course = next((c for c in courses if str(c.pk) == cid), courses[0] if courses else None)
    return render(request, "booking/book.html", {
        "courses": courses, "course": course, "cancel_days": settings.PROFESSOR_CANCEL_DAYS_BEFORE,
    })


@professor_required
@require_POST
def reserve(request):
    course = services.professor_courses(request.user).filter(pk=request.POST.get("course") or 0).first()
    slot = OpenSlot.objects.filter(pk=request.POST.get("slot") or 0).select_related("studio").first()
    back = reverse("booking:book") + (f"?course={course.pk}" if course else "")
    if not course or not slot:
        messages.error(request, "과목 또는 시간을 다시 선택해 주세요.")
        return redirect(back)
    if slot.studio_id != course.studio_id:
        messages.error(request, "이 과목에 지정된 스튜디오의 시간만 예약할 수 있습니다.")
        return redirect(back)
    try:
        r = services.book_slot(request.user, request.user, course, slot, memo=request.POST.get("memo", "")[:500])
    except ValidationError as e:
        messages.error(request, _errors(e))
        return redirect(back)
    messages.success(request, f"예약했습니다: {r.date:%Y-%m-%d} {r.start_time:%H:%M}~{r.end_time:%H:%M} {r.studio.name}")
    return redirect(back)


@professor_required
def my_reservations(request):
    today = timezone.localdate()
    qs = Reservation.objects.filter(professor=request.user).select_related("studio", "course")
    upcoming = qs.filter(date__gte=today, status=Reservation.Status.CONFIRMED).order_by("date", "start_time")
    past = qs.filter(
        Q(date__lt=today) | ~Q(status=Reservation.Status.CONFIRMED)
    ).order_by("-date", "-start_time")[:30]
    rows = [(r, services.professor_can_cancel(r), services.cancel_deadline(r)) for r in upcoming]
    return render(request, "booking/my_reservations.html", {"rows": rows, "past": past})


@professor_required
@require_POST
def my_cancel(request, pk):
    r = get_object_or_404(Reservation, pk=pk, professor=request.user)
    if not services.professor_can_cancel(r):
        messages.error(request, f"취소 기한({services.cancel_deadline(r):%m/%d})이 지났습니다. 스튜디오 담당자에게 문의해 주세요.")
    else:
        services.cancel_reservation(request.user, r, reason=request.POST.get("reason", ""))
        messages.success(request, f"{r.date:%m/%d} {r.start_time:%H:%M} 예약을 취소했습니다.")
    return redirect("booking:my_reservations")

from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.studios.models import CourseProfessor

from . import audit, services
from .forms import BlackoutForm, ReservationEditForm
from .models import AuditLog, Blackout, OpenSlot, Reservation
from .permissions import (
    editable_studios,
    require_edit,
    staff_required,
    viewable_studios,
)


def _pick_studio(request, studios):
    sid = request.GET.get("studio") or request.POST.get("studio")
    studio = studios.filter(pk=sid).first() if sid and sid.isdigit() else None
    return studio or studios.first()


# ── 현황 달력 ──────────────────────────────────────────────


@staff_required
def calendar(request):
    studios = viewable_studios(request.user)
    return render(request, "booking/calendar.html", {
        "studios": studios,
        "editable_ids": list(editable_studios(request.user).values_list("pk", flat=True)),
        "selected": request.GET.get("studio", ""),
    })


def _parse_range(request):
    def p(name, default):
        raw = (request.GET.get(name) or "")[:10]
        return parse_date(raw) or default

    start = p("start", timezone.localdate().replace(day=1))
    end = p("end", start + timedelta(days=42))
    return start, min(end, start + timedelta(days=100))


def _hhmm(d, t):
    return datetime.combine(d, t).isoformat(timespec="minutes")


@login_required
def events(request):
    """달력 데이터(JSON). 슬롯·예약·불가일을 FullCalendar 이벤트 형식으로 돌려준다.

    교수에게는 다른 교수의 이름·과목을 숨기고 "예약됨"으로만 보여준다.
    """
    user = request.user
    studios = viewable_studios(user)
    sid = request.GET.get("studio")
    if sid:
        studios = studios.filter(pk=sid) if sid.isdigit() else studios.none()
    start, end = _parse_range(request)
    is_manager = user.is_studio_staff or user.is_super_admin
    out = []

    reservations = list(Reservation.objects.filter(
        studio__in=studios, date__range=(start, end), status=Reservation.Status.CONFIRMED,
    ).select_related("studio", "professor", "course"))
    reserved_slot_ids = set()
    for r in reservations:
        reserved_slot_ids.add(r.slot_id)
        mine = r.professor_id == user.pk
        if is_manager or mine:
            title = f"{r.studio.code} {r.professor.name} · {r.course.name}"
        else:
            title = f"{r.studio.code} 예약됨"
        out.append({
            "id": f"r{r.pk}", "title": title,
            "start": _hhmm(r.date, r.start_time), "end": _hhmm(r.date, r.end_time),
            "color": r.studio.color,
            "extendedProps": {"kind": "reservation", "id": r.pk, "studio": r.studio_id, "mine": mine},
        })

    blackouts = list(Blackout.objects.filter(
        Q(studio__in=studios) | Q(studio__isnull=True), date__range=(start, end),
    ).select_related("studio"))
    today = timezone.localdate()
    for s in OpenSlot.objects.filter(studio__in=studios, date__range=(start, end)).select_related("studio"):
        # 예약·불가일과 겹치는 슬롯은 "예약 가능"으로 보이지 않게 한다.
        if s.pk in reserved_slot_ids or any(
            r.studio_id == s.studio_id and r.date == s.date
            and services.overlaps(r.start_time, r.end_time, s.start_time, s.end_time)
            for r in reservations
        ) or any(
            b.date == s.date and (b.studio_id in (None, s.studio_id))
            and (b.is_all_day or services.overlaps(b.start_time, b.end_time, s.start_time, s.end_time))
            for b in blackouts
        ):
            continue
        if not is_manager and s.date < today:
            continue
        out.append({
            "id": f"s{s.pk}", "title": " ".join(x for x in [s.studio.code, s.label, "예약 가능"] if x),
            "start": _hhmm(s.date, s.start_time), "end": _hhmm(s.date, s.end_time),
            "color": "#d1f0dc", "textColor": "#155d33", "borderColor": "#7ccf9b",
            "extendedProps": {"kind": "slot", "id": s.pk, "studio": s.studio_id, "past": s.date < today},
        })

    for b in blackouts:
        where = b.studio.code if b.studio else "전체"
        ev = {
            "id": f"b{b.pk}", "title": f"촬영 불가({where}) {b.reason}".strip(),
            "color": "#f8d7da", "textColor": "#842029", "borderColor": "#f1aeb5",
            "extendedProps": {"kind": "blackout", "id": b.pk},
        }
        if b.is_all_day:
            ev.update(start=b.date.isoformat(), allDay=True)
        else:
            ev.update(start=_hhmm(b.date, b.start_time), end=_hhmm(b.date, b.end_time))
        out.append(ev)
    return JsonResponse(out, safe=False)


# ── 주간 슬롯 설정 ─────────────────────────────────────────


@staff_required
def week_slots(request):
    studios = editable_studios(request.user)
    if not studios.exists():
        messages.warning(request, "담당 스튜디오가 없습니다. 슈퍼관리자에게 배정을 요청하세요.")
        return redirect("home")
    studio = _pick_studio(request, studios)
    raw = request.GET.get("week") or request.POST.get("week")
    monday = services.week_start(parse_date(raw) if raw and parse_date(raw) else timezone.localdate())

    if request.method == "POST":
        require_edit(request.user, studio)
        if "copy_prev" in request.POST:
            res = services.copy_previous_week(request.user, studio, monday)
            messages.success(request, f"지난주 슬롯 {res.created}개를 복사했습니다.")
        else:
            checked = set(request.POST.getlist("cell"))
            with transaction.atomic():
                res = services.save_week(request.user, studio, monday, checked)
            messages.success(request, f"저장했습니다. 추가 {res.created}개, 삭제 {res.deleted}개.")
            if res.kept_reserved:
                messages.warning(request, f"예약이 있는 슬롯 {res.kept_reserved}개는 지우지 않았습니다. 예약을 먼저 취소하세요.")
        if res.conflicts:
            messages.warning(request, "다른 슬롯과 시간이 겹쳐 건너뛴 칸: " + ", ".join(res.conflicts))
        return redirect(f"{request.path}?studio={studio.pk}&week={monday.isoformat()}")

    grid = services.build_week_grid(studio, monday)
    return render(request, "booking/week_slots.html", {
        "studios": studios, "studio": studio, "grid": grid, "monday": monday,
        "sunday": monday + timedelta(days=6),
        "prev_week": monday - timedelta(days=7), "next_week": monday + timedelta(days=7),
    })


# ── 촬영 불가일 ────────────────────────────────────────────


@staff_required
def blackouts(request):
    user = request.user
    studios = editable_studios(user)
    form = BlackoutForm(request.POST or None, user=user, studios=studios)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        require_edit(user, d["studio"])
        with transaction.atomic():
            created, conflicts = services.create_blackouts(
                user, d["studio"], d["start_date"], d["end_date"], d["start_time"], d["end_time"], d["reason"],
            )
        messages.success(request, f"촬영 불가일 {len(created)}일을 등록했습니다.")
        if conflicts:
            lines = ", ".join(f"{r.date:%m/%d} {r.start_time:%H:%M} {r.studio.code} {r.professor.name}" for r in conflicts)
            messages.warning(request, f"이 기간에 확정 예약 {len(conflicts)}건이 있습니다. 확인 후 조정하세요: {lines}")
        return redirect("booking:blackouts")

    upcoming = Blackout.objects.filter(date__gte=timezone.localdate()).filter(
        Q(studio__in=viewable_studios(user)) | Q(studio__isnull=True)
    ).select_related("studio").order_by("date", "start_time")
    editable_ids = set(studios.values_list("pk", flat=True))
    rows = [(b, (b.studio_id in editable_ids) if b.studio_id else user.is_super_admin) for b in upcoming]
    return render(request, "booking/blackouts.html", {"form": form, "rows": rows})


@staff_required
@require_POST
def blackout_delete(request, pk):
    b = get_object_or_404(Blackout, pk=pk)
    require_edit(request.user, b.studio)
    before = audit.snapshot(b)
    b.delete()
    b.pk = pk
    audit.log(request.user, AuditLog.Action.DELETE, b, before=before)
    messages.success(request, "촬영 불가일을 삭제했습니다.")
    return redirect("booking:blackouts")


# ── 예약 관리 ──────────────────────────────────────────────


@staff_required
def reservations(request):
    user = request.user
    studios = viewable_studios(user)
    qs = Reservation.objects.filter(studio__in=studios).select_related("studio", "professor", "course")
    start = parse_date(request.GET.get("start") or "") or timezone.localdate()
    end = parse_date(request.GET.get("end") or "") or start + timedelta(days=30)
    qs = qs.filter(date__range=(start, end))
    sid = request.GET.get("studio")
    if sid and sid.isdigit():
        qs = qs.filter(studio_id=sid)
    if request.GET.get("status") != "all":
        qs = qs.filter(status=Reservation.Status.CONFIRMED)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(professor__name__icontains=q) | Q(course__name__icontains=q))
    editable_ids = set(editable_studios(user).values_list("pk", flat=True))
    return render(request, "booking/reservations.html", {
        "rows": [(r, r.studio_id in editable_ids) for r in qs.order_by("date", "start_time")],
        "studios": studios, "start": start, "end": end, "sid": sid or "", "q": q,
        "status": request.GET.get("status", ""),
    })


@staff_required
def reservation_edit(request, pk):
    r = get_object_or_404(Reservation.objects.select_related("studio", "professor", "course"), pk=pk)
    require_edit(request.user, r.studio)
    before = audit.snapshot(r)
    form = ReservationEditForm(request.POST or None, instance=r, studios=editable_studios(request.user))
    if request.method == "POST" and form.is_valid():
        r = form.save(commit=False)
        r.updated_by = request.user
        try:
            with transaction.atomic():
                r.save()
        except IntegrityError:
            form.add_error(None, "이미 예약된 시간입니다.")
        else:
            audit.log(request.user, AuditLog.Action.UPDATE, r, before=before, after=audit.snapshot(r))
            messages.success(request, "예약을 수정했습니다.")
            return redirect("booking:reservations")
    history = AuditLog.objects.filter(target_table=r._meta.db_table, target_id=r.pk).select_related("user")[:20]
    return render(request, "booking/reservation_edit.html", {"form": form, "r": r, "history": history})


@staff_required
@require_POST
def reservation_cancel(request, pk):
    r = get_object_or_404(Reservation, pk=pk)
    require_edit(request.user, r.studio)
    if r.status == Reservation.Status.CANCELLED:
        messages.info(request, "이미 취소된 예약입니다.")
    else:
        before = audit.snapshot(r)
        r.status = Reservation.Status.CANCELLED
        r.updated_by = request.user
        r.save(update_fields=["status", "updated_by", "updated_at"])
        audit.log(request.user, AuditLog.Action.CANCEL, r, before=before, after=audit.snapshot(r))
        messages.success(request, f"{r.date:%m/%d} {r.start_time:%H:%M} 예약을 취소했습니다.")
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("booking:reservations")


@staff_required
def reservation_new(request):
    """담당자 대리 예약: 열린 슬롯 하나에 과목·교수를 골라 예약한다."""
    slot = get_object_or_404(OpenSlot.objects.select_related("studio"), pk=request.GET.get("slot") or request.POST.get("slot") or 0)
    require_edit(request.user, slot.studio)
    pairs = list(
        CourseProfessor.objects.filter(course__studio=slot.studio, course__is_active=True)
        .select_related("course", "professor").order_by("course__name", "professor__name")
    )
    if request.method == "POST":
        pair = next((p for p in pairs if str(p.pk) == request.POST.get("pair")), None)
        if pair is None:
            messages.error(request, "과목·교수를 선택해 주세요.")
        else:
            try:
                services.book_slot(request.user, pair.professor, pair.course, slot, memo=request.POST.get("memo", "")[:500])
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            else:
                messages.success(request, f"{pair.professor.name} 교수 예약을 등록했습니다.")
                return redirect("booking:calendar")
    return render(request, "booking/reservation_new.html", {"slot": slot, "pairs": pairs})

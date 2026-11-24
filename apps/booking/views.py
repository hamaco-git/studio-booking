from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.notify.services import current_mode as sms_mode
from apps.notify.services import notify_on_commit
from apps.studios.models import CourseProfessor

from . import audit, services
from .forms import BlackoutForm, ReservationEditForm
from .models import AuditLog, Blackout, OpenSlot, Reservation
from .permissions import (
    editable_studios,
    require_edit,
    schedule_viewer_required,
    staff_required,
    viewable_studios,
)


def _designers():
    from apps.accounts.models import User

    return User.objects.filter(role=User.Role.DESIGNER, is_active=True).order_by("name")


def _designer_filter(request):
    """담당자·슈퍼관리자가 고른 교수설계자 ID (교수설계자 본인은 항상 자기 과목만 본다)."""
    if request.user.is_designer:
        return None
    did = request.GET.get("designer") or ""
    return did if did.isdigit() else None


def _pick_studio(request, studios):
    sid = request.GET.get("studio") or request.POST.get("studio")
    studio = studios.filter(pk=sid).first() if sid and sid.isdigit() else None
    return studio or studios.first()


# ── 현황 달력 ──────────────────────────────────────────────


@schedule_viewer_required
def calendar(request):
    studios = viewable_studios(request.user)
    return render(request, "booking/calendar.html", {
        "studios": studios,
        "editable_ids": list(editable_studios(request.user).values_list("pk", flat=True)),
        "selected": request.GET.get("studio", ""),
        "designers": [] if request.user.is_designer else _designers(),
        "selected_designer": _designer_filter(request) or "",
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
    교수설계자에게는 담당 과목의 예약과 촬영 불가일만 보여준다 (예약 가능 슬롯은 숨김).
    """
    user = request.user
    studios = viewable_studios(user)
    sid = request.GET.get("studio")
    if sid:
        studios = studios.filter(pk=sid) if sid.isdigit() else studios.none()
    start, end = _parse_range(request)
    is_manager = user.is_studio_staff or user.is_super_admin
    show_detail = is_manager or user.is_designer
    did = _designer_filter(request) if is_manager else None
    out = []

    reservations = Reservation.objects.filter(
        studio__in=studios, date__range=(start, end), status__in=Reservation.ACTIVE_STATUSES,
    ).select_related("studio", "professor", "course")
    if user.is_designer:
        reservations = reservations.filter(course__designer=user)
    elif did:
        reservations = reservations.filter(course__designer_id=did)
    reservations = list(reservations)
    reserved_slot_ids = set()
    for r in reservations:
        reserved_slot_ids.add(r.slot_id)
        mine = r.professor_id == user.pk
        if show_detail or mine:
            title = f"{r.studio.code} {r.professor.name} · {r.course.name}"
            if show_detail and r.status == Reservation.Status.NO_SHOW:
                title = f"[노쇼] {title}"
            elif show_detail and r.status == Reservation.Status.COMPLETED:
                title = f"[완료] {title}"
        else:
            title = f"{r.studio.code} 예약됨"
        out.append({
            "id": f"r{r.pk}", "title": title,
            "start": _hhmm(r.date, r.start_time), "end": _hhmm(r.date, r.end_time),
            "color": r.studio.color,
            "extendedProps": {"kind": "reservation", "id": r.pk, "studio": r.studio_id, "mine": mine,
                              "status": r.status if (show_detail or mine) else "",
                              # 교수 메모는 담당자·관리자·교수설계자와 본인에게만 보낸다.
                              "memo": r.memo.strip() if (show_detail or mine) else ""},
        })

    blackouts = list(Blackout.objects.filter(
        Q(studio__in=studios) | Q(studio__isnull=True), date__range=(start, end),
    ).select_related("studio"))
    today = timezone.localdate()
    slots = OpenSlot.objects.filter(studio__in=studios, date__range=(start, end)).select_related("studio")
    if user.is_designer or did:
        # 교수설계자 일정 보기에서는 예약 가능 슬롯 대신 촬영 일정만 보여준다.
        slots = slots.none()
    for s in slots:
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


STATUS_FILTERS = [
    ("", "취소 제외 전체"),
    ("CONFIRMED", "확정"),
    ("pending", "처리 전 (촬영일 지남)"),
    ("COMPLETED", "촬영 완료"),
    ("NO_SHOW", "불참(노쇼)"),
    ("CANCELLED", "취소"),
    ("all", "취소 포함 전체"),
]


def _filtered_reservations(request):
    """예약 목록·엑셀 내려받기 공통 조건."""
    studios = viewable_studios(request.user)
    qs = Reservation.objects.filter(studio__in=studios).select_related("studio", "professor", "course")
    start = parse_date(request.GET.get("start") or "") or timezone.localdate()
    end = parse_date(request.GET.get("end") or "") or start + timedelta(days=30)
    qs = qs.filter(date__range=(start, end))
    sid = request.GET.get("studio")
    if sid and sid.isdigit():
        qs = qs.filter(studio_id=sid)
    status = request.GET.get("status", "")
    if status == "all":
        pass
    elif status == "pending":
        qs = qs.filter(status=Reservation.Status.CONFIRMED, date__lt=timezone.localdate())
    elif status in Reservation.Status.values:
        qs = qs.filter(status=status)
    else:
        status = ""
        qs = qs.filter(status__in=Reservation.ACTIVE_STATUSES)
    pid = request.GET.get("professor")
    if pid and pid.isdigit():
        qs = qs.filter(professor_id=pid)
    if request.user.is_designer:
        qs = qs.filter(course__designer=request.user)
    did = _designer_filter(request)
    if did:
        qs = qs.filter(course__designer_id=did)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(professor__name__icontains=q) | Q(course__name__icontains=q))
    ctx = {"studios": studios, "start": start, "end": end, "sid": sid or "", "q": q,
           "status": status, "professor": pid or "", "status_choices": STATUS_FILTERS,
           "designers": [] if request.user.is_designer else _designers(), "designer": did or ""}
    return qs.order_by("date", "start_time", "studio__code"), ctx


@schedule_viewer_required
def reservations(request):
    qs, ctx = _filtered_reservations(request)
    editable_ids = set(editable_studios(request.user).values_list("pk", flat=True))
    today = timezone.localdate()
    ctx["rows"] = [(r, r.studio_id in editable_ids, r.can_mark_attendance(today)) for r in qs]
    ctx["query"] = request.GET.urlencode()
    ctx["next"] = request.get_full_path()
    return render(request, "booking/reservations.html", ctx)


@schedule_viewer_required
def reservations_export(request):
    """예약 목록을 엑셀(xlsx)로 내려받기. 화면의 조회 조건을 그대로 사용한다."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    qs, ctx = _filtered_reservations(request)
    wb = Workbook()
    ws = wb.active
    ws.title = "예약"
    headers = ["날짜", "요일", "시작", "종료", "스튜디오", "교수", "과목", "교수설계자", "상태", "메모", "등록자", "등록일시",
               "취소 일시", "취소한 사람", "취소 사유"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    days = "월화수목금토일"
    for r in qs.select_related("created_by", "cancelled_by", "course__designer"):
        ws.append([
            r.date, days[r.date.weekday()], r.start_time.strftime("%H:%M"), r.end_time.strftime("%H:%M"),
            r.studio.name, r.professor.name, r.course.name,
            r.course.designer.name if r.course.designer else "", r.get_status_display(), r.memo,
            r.created_by.name if r.created_by else "",
            timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(r.cancelled_at).strftime("%Y-%m-%d %H:%M") if r.cancelled_at else "",
            r.cancelled_by.name if r.cancelled_by else "", r.cancel_reason,
        ])
    for i, w in enumerate([12, 5, 7, 7, 12, 12, 24, 12, 10, 30, 12, 17, 17, 12, 30], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_col=1):
        row[0].number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    name = f"reservations_{ctx['start']:%Y%m%d}-{ctx['end']:%Y%m%d}.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    wb.save(resp)
    return resp


@staff_required
def reservation_edit(request, pk):
    r = get_object_or_404(Reservation.objects.select_related("studio", "professor", "course", "cancelled_by"), pk=pk)
    require_edit(request.user, r.studio)
    before = audit.snapshot(r)
    editable = r.status == Reservation.Status.CONFIRMED
    form = ReservationEditForm(request.POST or None, instance=r, studios=editable_studios(request.user)) if editable else None
    if request.method == "POST" and not editable:
        messages.error(request, f"{r.get_status_display()} 상태의 예약은 시간을 바꿀 수 없습니다.")
        return redirect("booking:reservation_edit", pk=r.pk)
    if request.method == "POST" and form.is_valid():
        r = form.save(commit=False)
        r.updated_by = request.user
        try:
            with transaction.atomic():
                r.save()
        except IntegrityError:
            form.add_error(None, "이미 예약된 시간입니다.")
        else:
            after = audit.snapshot(r)
            audit.log(request.user, AuditLog.Action.UPDATE, r, before=before, after=after)
            msg = "예약을 수정했습니다."
            if any(before.get(k) != after.get(k) for k in ("studio", "date", "start_time", "end_time")):
                notify_on_commit(r, "CHANGED")  # 일정이 바뀌면 교수에게 변경 안내 문자
                if sms_mode() != "off":
                    msg += " 교수님께 변경 안내 문자도 발송합니다."
            messages.success(request, msg)
            return redirect("booking:reservations")
    display = audit._Display()
    history = [
        (h, audit.changes_text(h, display) if h.action != AuditLog.Action.CREATE else "")
        for h in AuditLog.objects.filter(target_table=r._meta.db_table, target_id=r.pk).select_related("user")[:30]
    ]
    return render(request, "booking/reservation_edit.html", {
        "form": form, "r": r, "history": history, "can_mark": r.can_mark_attendance(),
        "sms_logs": r.sms_logs.all()[:20],
    })


@staff_required
@require_POST
def reservation_cancel(request, pk):
    r = get_object_or_404(Reservation.objects.select_related("studio", "professor", "course"), pk=pk)
    require_edit(request.user, r.studio)
    try:
        services.cancel_reservation(request.user, r, reason=request.POST.get("reason", ""))
    except ValidationError as e:
        messages.info(request, " ".join(e.messages))
    else:
        notify_on_commit(r, "CANCELLED", reason=r.cancel_reason)  # 담당자가 취소하면 교수에게 안내 문자
        messages.success(request, f"{r.date:%m/%d} {r.start_time:%H:%M} 예약을 취소했습니다.")
    return _back(request, "booking:reservations")


def _back(request, default):
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(default)


@staff_required
@require_POST
def reservation_status(request, pk):
    """촬영 완료 / 불참(노쇼) 표시, 확정으로 되돌리기."""
    r = get_object_or_404(Reservation.objects.select_related("studio", "professor", "course"), pk=pk)
    require_edit(request.user, r.studio)
    status = request.POST.get("status", "")
    try:
        changed = services.set_attendance(request.user, r, status)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        if changed:
            messages.success(request, f"{r.date:%m/%d} {r.start_time:%H:%M} {r.professor.name} 예약을 "
                                      f"'{r.get_status_display()}'(으)로 표시했습니다.")
    return _back(request, "booking:reservations")


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


# ── 노쇼·취소 기록 ─────────────────────────────────────────


@staff_required
def records(request):
    """기간별 교수 출결(촬영 완료·노쇼)·취소 집계와 노쇼·취소 상세 기록."""
    from django.db.models import Count

    from apps.studios.models import Semester

    today = timezone.localdate()
    sem = Semester.objects.filter(is_current=True).first()
    default_start = sem.start_date if sem else today - timedelta(days=90)
    default_end = min(sem.end_date, today) if sem and sem.end_date >= sem.start_date else today
    start = parse_date(request.GET.get("start") or "") or default_start
    end = parse_date(request.GET.get("end") or "") or max(default_end, start)
    studios = viewable_studios(request.user)
    qs = Reservation.objects.filter(studio__in=studios, date__range=(start, end))
    sid = request.GET.get("studio")
    if sid and sid.isdigit():
        qs = qs.filter(studio_id=sid)

    S = Reservation.Status
    summary = list(
        qs.values("professor_id", "professor__name").annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=S.COMPLETED)),
            no_show=Count("id", filter=Q(status=S.NO_SHOW)),
            cancelled=Count("id", filter=Q(status=S.CANCELLED)),
            cancelled_by_staff=Count("id", filter=Q(status=S.CANCELLED) & ~Q(cancelled_by=F("professor"))),
            pending=Count("id", filter=Q(status=S.CONFIRMED, date__lt=today)),
        ).order_by("-no_show", "-cancelled", "professor__name")
    )
    totals = {k: sum(row[k] for row in summary)
              for k in ("total", "completed", "no_show", "cancelled", "pending")}
    details = qs.filter(status__in=[S.NO_SHOW, S.CANCELLED]).select_related(
        "studio", "professor", "course", "cancelled_by",
    ).order_by("-date", "-start_time")[:300]
    return render(request, "booking/records.html", {
        "studios": studios, "sid": sid or "", "start": start, "end": end, "semester": sem,
        "summary": summary, "totals": totals, "details": details,
    })

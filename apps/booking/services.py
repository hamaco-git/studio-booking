"""주간 슬롯 설정, 불가일 등록 같은 업무 로직."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q

from . import audit
from .models import AuditLog, Blackout, OpenSlot, Reservation, SlotTemplate

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def week_start(d: date) -> date:
    """d가 속한 주의 월요일."""
    return d - timedelta(days=d.weekday())


def week_days(monday: date):
    return [monday + timedelta(days=i) for i in range(7)]


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@dataclass
class WeekCell:
    day: date
    template: SlotTemplate
    slot: OpenSlot | None = None
    reserved: bool = False
    blackout: bool = False

    @property
    def key(self):
        return f"{self.day.isoformat()}_{self.template.pk}"


@dataclass
class WeekGrid:
    studio: object
    monday: date
    templates: list
    rows: list = field(default_factory=list)  # [(day, [WeekCell...])]
    other_slots: list = field(default_factory=list)  # 템플릿과 시간이 다른 기존 슬롯


def build_week_grid(studio, monday):
    days = week_days(monday)
    templates = list(SlotTemplate.objects.filter(is_active=True))
    slots = list(OpenSlot.objects.filter(studio=studio, date__range=(days[0], days[-1])))
    reserved_ids = set(
        Reservation.objects.filter(slot__in=slots, status__in=Reservation.ACTIVE_STATUSES).values_list("slot_id", flat=True)
    )
    blackouts = list(
        Blackout.objects.filter(Q(studio=studio) | Q(studio__isnull=True), date__range=(days[0], days[-1]))
    )
    grid = WeekGrid(studio=studio, monday=monday, templates=templates)
    matched = set()
    for d in days:
        cells = []
        for t in templates:
            slot = next(
                (s for s in slots if s.date == d and s.start_time == t.start_time and s.end_time == t.end_time), None
            )
            if slot:
                matched.add(slot.pk)
            blocked = any(
                b.date == d and (b.is_all_day or overlaps(b.start_time, b.end_time, t.start_time, t.end_time))
                for b in blackouts
            )
            cells.append(WeekCell(d, t, slot, bool(slot and slot.pk in reserved_ids), blocked))
        grid.rows.append((d, WEEKDAYS[d.weekday()], cells))
    grid.other_slots = [s for s in slots if s.pk not in matched]
    return grid


@dataclass
class SaveResult:
    created: int = 0
    deleted: int = 0
    kept_reserved: int = 0
    conflicts: list = field(default_factory=list)


def save_week(user, studio, monday, checked_keys):
    """체크된 칸은 슬롯을 만들고, 체크 해제된 칸의 슬롯은 지운다.

    예약이 있는 슬롯은 지우지 않는다. 시간이 겹치는 칸은 건너뛰고 conflicts에 담는다.
    """
    grid = build_week_grid(studio, monday)
    result = SaveResult()
    for _day, _wd, cells in grid.rows:
        for cell in cells:
            want = cell.key in checked_keys
            if cell.slot and not want:
                if cell.reserved:
                    result.kept_reserved += 1
                    continue
                before = audit.snapshot(cell.slot)
                pk = cell.slot.pk
                cell.slot.delete()
                cell.slot.pk = pk
                audit.log(user, AuditLog.Action.DELETE, cell.slot, before=before)
                result.deleted += 1
    for _day, _wd, cells in grid.rows:
        for cell in cells:
            if cell.key in checked_keys and not cell.slot:
                if _create_slot(user, studio, cell.day, cell.template, result):
                    result.created += 1
    return result


def _create_slot(user, studio, day, template, result):
    try:
        with transaction.atomic():
            slot = OpenSlot.objects.create(
                studio=studio, date=day, start_time=template.start_time, end_time=template.end_time,
                label=template.label, created_by=user,
            )
    except IntegrityError:
        result.conflicts.append(f"{day:%m/%d} {template.label}")
        return False
    audit.log(user, AuditLog.Action.CREATE, slot, after=audit.snapshot(slot))
    return True


def copy_previous_week(user, studio, monday):
    """지난주 슬롯을 같은 요일·시간으로 이번 주에 복사 (이미 있거나 겹치면 건너뜀)."""
    prev = monday - timedelta(days=7)
    result = SaveResult()
    for s in OpenSlot.objects.filter(studio=studio, date__range=(prev, prev + timedelta(days=6))):
        template = SlotTemplate(label=s.label, start_time=s.start_time, end_time=s.end_time)
        day = s.date + timedelta(days=7)
        if OpenSlot.objects.filter(studio=studio, date=day, start_time=s.start_time, end_time=s.end_time).exists():
            continue
        if _create_slot(user, studio, day, template, result):
            result.created += 1
    return result


def create_blackouts(user, studio, start, end, start_time, end_time, reason):
    """기간(start~end)의 날짜마다 불가일을 만들고, 겹치는 확정 예약 목록을 돌려준다."""
    created = []
    d = start
    while d <= end:
        b = Blackout.objects.create(
            studio=studio, date=d, start_time=start_time, end_time=end_time, reason=reason, created_by=user,
        )
        audit.log(user, AuditLog.Action.CREATE, b, after=audit.snapshot(b))
        created.append(b)
        d += timedelta(days=1)
    conflicts = Reservation.objects.filter(status=Reservation.Status.CONFIRMED, date__range=(start, end))
    if studio:
        conflicts = conflicts.filter(studio=studio)
    if start_time:
        conflicts = conflicts.filter(start_time__lt=end_time, end_time__gt=start_time)
    return created, list(conflicts.select_related("studio", "professor", "course"))


# ── 예약 신청·취소 ────────────────────────────────────────


def professor_courses(professor):
    """교수가 예약할 수 있는 과목 (사용 중인 과목, 사용 중인 스튜디오)."""
    from apps.studios.models import Course

    return Course.objects.filter(
        professors=professor, is_active=True, studio__is_active=True,
    ).select_related("studio", "semester").order_by("name")


def book_slot(actor, professor, course, slot, memo=""):
    """슬롯 하나를 예약한다. actor는 교수 본인 또는 대리 예약하는 담당자.

    규칙 위반이면 ValidationError, 동시에 다른 사람이 먼저 예약하면 ValidationError("이미 예약된…").
    """
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if slot.date < timezone.localdate():
        raise ValidationError("지난 날짜는 예약할 수 없습니다.")
    r = Reservation(
        studio=slot.studio, course=course, professor=professor, slot=slot,
        date=slot.date, start_time=slot.start_time, end_time=slot.end_time,
        memo=memo, created_by=actor, updated_by=actor,
    )
    r.full_clean()
    try:
        with transaction.atomic():
            r.save()
    except IntegrityError:
        raise ValidationError("방금 다른 분이 먼저 예약했습니다. 다른 시간을 선택해 주세요.")
    audit.log(actor, AuditLog.Action.CREATE, r, after=audit.snapshot(r))
    return r


def cancel_deadline(reservation):
    """교수 본인이 취소할 수 있는 마지막 날짜 (촬영일 N일 전)."""
    from django.conf import settings

    return reservation.date - timedelta(days=settings.PROFESSOR_CANCEL_DAYS_BEFORE)


def professor_can_cancel(reservation):
    from django.utils import timezone

    return (
        reservation.status == Reservation.Status.CONFIRMED
        and timezone.localdate() <= cancel_deadline(reservation)
    )


def cancel_reservation(actor, reservation, reason=""):
    """예약을 취소 상태로 바꾼다 (삭제하지 않음). 확정 상태만 취소할 수 있다."""
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if reservation.status != Reservation.Status.CONFIRMED:
        raise ValidationError(f"{reservation.get_status_display()} 상태의 예약은 취소할 수 없습니다.")
    before = audit.snapshot(reservation)
    reservation.status = Reservation.Status.CANCELLED
    reservation.cancelled_at = timezone.now()
    reservation.cancelled_by = actor
    reservation.cancel_reason = (reason or "").strip()[:200]
    reservation.updated_by = actor
    reservation.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason", "updated_by", "updated_at"])
    audit.log(actor, AuditLog.Action.CANCEL, reservation, before=before, after=audit.snapshot(reservation))


def set_attendance(actor, reservation, status):
    """촬영 완료 / 불참(노쇼) 표시, 또는 확정으로 되돌리기.

    촬영일 당일부터 표시할 수 있고, 취소된 예약은 바꿀 수 없다.
    """
    from django.core.exceptions import ValidationError

    allowed = (Reservation.Status.CONFIRMED, *Reservation.ATTENDANCE_STATUSES)
    if status not in allowed:
        raise ValidationError("바꿀 수 없는 상태입니다.")
    if not reservation.is_active:
        raise ValidationError("취소된 예약은 상태를 바꿀 수 없습니다.")
    if status != Reservation.Status.CONFIRMED and not reservation.can_mark_attendance():
        raise ValidationError("촬영 완료·불참은 촬영일 당일부터 표시할 수 있습니다.")
    if reservation.status == status:
        return False
    before = audit.snapshot(reservation)
    reservation.status = status
    reservation.updated_by = actor
    reservation.save(update_fields=["status", "updated_by", "updated_at"])
    audit.log(actor, AuditLog.Action.STATUS, reservation, before=before, after=audit.snapshot(reservation))
    return True

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
        Reservation.objects.filter(slot__in=slots, status=Reservation.Status.CONFIRMED).values_list("slot_id", flat=True)
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

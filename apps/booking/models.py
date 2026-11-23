from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ExpressionWrapper, F, Func, Q

from apps.studios.models import Course, Studio


class TsRange(Func):
    """PostgreSQL tsrange(시작, 끝) — 날짜+시간 구간 겹침 검사용."""

    function = "TSRANGE"
    output_field = DateTimeRangeField()


def _ts(time_field):
    # date + time → timestamp (PostgreSQL)
    return ExpressionWrapper(F("date") + F(time_field), output_field=models.DateTimeField())


TIME_RANGE = TsRange(_ts("start_time"), _ts("end_time"))


class SlotTemplate(models.Model):
    """주간 슬롯 설정 화면에 나오는 시간대 (예: 오전 09:00~12:00, 오후 13:00~18:00).

    슈퍼관리자가 관리자 화면에서 바꿀 수 있다.
    """

    label = models.CharField("이름", max_length=20)
    start_time = models.TimeField("시작")
    end_time = models.TimeField("종료")
    order = models.PositiveSmallIntegerField("순서", default=0)
    is_active = models.BooleanField("사용 중", default=True)

    class Meta:
        verbose_name = "시간대 템플릿"
        verbose_name_plural = "시간대 템플릿"
        ordering = ["order", "start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="template_time_valid"),
        ]

    def __str__(self):
        return f"{self.label} {self.start_time:%H:%M}~{self.end_time:%H:%M}"


class OpenSlot(models.Model):
    """담당자가 연 예약 가능 시간대 슬롯 (예: 오전 09:00~12:00).

    주간 운영일 설정 화면에서 한 주를 골라 요일·시간대를 체크하면
    날짜별로 한 행씩 저장된다. 같은 스튜디오의 슬롯끼리는 겹칠 수 없다.
    """

    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, verbose_name="스튜디오")
    date = models.DateField("날짜")
    start_time = models.TimeField("시작")
    end_time = models.TimeField("종료")
    label = models.CharField("이름", max_length=20, blank=True, help_text="예: 오전, 오후, 종일")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+", verbose_name="등록자",
    )
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        verbose_name = "예약 가능 슬롯"
        verbose_name_plural = "예약 가능 슬롯"
        ordering = ["date", "start_time", "studio"]
        indexes = [models.Index(fields=["studio", "date"])]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="slot_time_valid"),
            ExclusionConstraint(
                name="slot_no_overlap",
                expressions=[(F("studio"), RangeOperators.EQUAL), (TIME_RANGE, RangeOperators.OVERLAPS)],
            ),
        ]

    def __str__(self):
        label = f" {self.label}" if self.label else ""
        return f"{self.studio} {self.date}{label} {self.start_time:%H:%M}~{self.end_time:%H:%M}"


class Blackout(models.Model):
    """촬영 불가일. 스튜디오를 비우면 전체 스튜디오, 시간을 비우면 종일."""

    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, null=True, blank=True,
        verbose_name="스튜디오", help_text="비우면 모든 스튜디오",
    )
    date = models.DateField("날짜")
    start_time = models.TimeField("시작", null=True, blank=True, help_text="비우면 종일")
    end_time = models.TimeField("종료", null=True, blank=True)
    reason = models.CharField("사유", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+", verbose_name="등록자",
    )
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        verbose_name = "촬영 불가일"
        verbose_name_plural = "촬영 불가일"
        ordering = ["date"]
        indexes = [models.Index(fields=["date"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(start_time__isnull=True, end_time__isnull=True)
                    | Q(start_time__isnull=False, end_time__isnull=False, end_time__gt=F("start_time"))
                ),
                name="blackout_time_valid",
            ),
        ]

    def __str__(self):
        where = self.studio or "전체 스튜디오"
        return f"{where} {self.date} {self.reason}".strip()

    @property
    def is_all_day(self):
        return self.start_time is None


class Reservation(models.Model):
    """촬영 예약. 삭제하지 않고 상태를 바꿔 기록으로 남긴다.

    확정 → 촬영 완료 / 불참(노쇼): 촬영일 당일부터 담당자가 표시
    확정 → 취소: 교수 본인(기한 내) 또는 담당자. 취소 일시·사유·취소한 사람을 남긴다.

    같은 스튜디오의 취소되지 않은 예약끼리는 시간이 겹칠 수 없으며,
    이는 DB 제약(slot_no_overlap과 같은 방식)으로 강제되어 동시 예약도 막는다.
    """

    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "확정"
        COMPLETED = "COMPLETED", "촬영 완료"
        NO_SHOW = "NO_SHOW", "불참(노쇼)"
        CANCELLED = "CANCELLED", "취소"

    # 시간을 차지하는(취소되지 않은) 상태
    ACTIVE_STATUSES = (Status.CONFIRMED, Status.COMPLETED, Status.NO_SHOW)
    # 담당자가 촬영 당일부터 표시하는 출결 상태
    ATTENDANCE_STATUSES = (Status.COMPLETED, Status.NO_SHOW)

    studio = models.ForeignKey(Studio, on_delete=models.PROTECT, verbose_name="스튜디오")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, verbose_name="과목")
    professor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="reservations", verbose_name="교수",
    )
    slot = models.ForeignKey(
        OpenSlot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reservations", verbose_name="슬롯",
    )
    date = models.DateField("날짜")
    start_time = models.TimeField("시작")
    end_time = models.TimeField("종료")
    status = models.CharField("상태", max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    memo = models.TextField("메모", blank=True)
    cancelled_at = models.DateTimeField("취소 일시", null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        related_name="+", verbose_name="취소한 사람",
    )
    cancel_reason = models.CharField("취소 사유", max_length=200, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+", verbose_name="등록자",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+", verbose_name="수정자",
    )
    created_at = models.DateTimeField("등록일시", auto_now_add=True)
    updated_at = models.DateTimeField("수정일시", auto_now=True)

    class Meta:
        verbose_name = "예약"
        verbose_name_plural = "예약"
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["studio", "date"]),
            models.Index(fields=["professor", "date"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="reservation_time_valid"),
            ExclusionConstraint(
                name="reservation_no_overlap",
                expressions=[(F("studio"), RangeOperators.EQUAL), (TIME_RANGE, RangeOperators.OVERLAPS)],
                condition=~Q(status="CANCELLED"),
            ),
        ]

    def __str__(self):
        return f"{self.studio} {self.date} {self.start_time:%H:%M}~{self.end_time:%H:%M} {self.professor.name}"

    def clean(self):
        """예약 규칙 검사 (폼·관리자 화면에서 호출)."""
        errors = []
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError("종료 시간은 시작 시간보다 늦어야 합니다.")
        if not (self.studio_id and self.date and self.start_time and self.end_time):
            return

        if self.course_id and self.course.studio_id != self.studio_id:
            errors.append("이 과목에 지정된 스튜디오가 아닙니다.")
        if self.course_id and self.professor_id and not self.course.professors.filter(pk=self.professor_id).exists():
            errors.append("이 교수가 담당하는 과목이 아닙니다.")

        in_slot = OpenSlot.objects.filter(
            studio_id=self.studio_id, date=self.date,
            start_time__lte=self.start_time, end_time__gte=self.end_time,
        ).exists()
        if not in_slot:
            errors.append("담당자가 열어 둔 예약 가능 시간이 아닙니다.")

        blackout = Blackout.objects.filter(
            Q(studio_id=self.studio_id) | Q(studio__isnull=True), date=self.date,
        ).filter(
            Q(start_time__isnull=True)
            | Q(start_time__lt=self.end_time, end_time__gt=self.start_time)
        )
        if blackout.exists():
            errors.append("촬영 불가일로 지정된 시간입니다.")

        if self.status != self.Status.CANCELLED:
            overlap = Reservation.objects.filter(
                studio_id=self.studio_id, date=self.date, status__in=self.ACTIVE_STATUSES,
                start_time__lt=self.end_time, end_time__gt=self.start_time,
            ).exclude(pk=self.pk)
            if overlap.exists():
                errors.append("이미 예약된 시간입니다.")

        if errors:
            raise ValidationError(errors)

    @property
    def is_active(self):
        return self.status != self.Status.CANCELLED

    @property
    def needs_attendance(self):
        """촬영일이 지났는데 아직 완료/노쇼 표시가 안 된 예약."""
        from django.utils import timezone

        return self.status == self.Status.CONFIRMED and self.date < timezone.localdate()

    def can_mark_attendance(self, today=None):
        from django.utils import timezone

        return self.is_active and self.date <= (today or timezone.localdate())

    def describe(self):
        """이력에 남길 한 줄 설명 (예: studio1 2026-12-01 09:00~12:00 홍길동 · 영상제작론)."""
        return (f"{self.studio.code} {self.date:%Y-%m-%d} {self.start_time:%H:%M}~{self.end_time:%H:%M} "
                f"{self.professor.name} · {self.course.name}")


class AuditLog(models.Model):
    """작업 이력: 누가 언제 무엇(예약·슬롯·불가일·과목·계정)을 생성·수정·취소·상태 변경했는지."""

    class Action(models.TextChoices):
        CREATE = "CREATE", "생성"
        UPDATE = "UPDATE", "수정"
        DELETE = "DELETE", "삭제"
        CANCEL = "CANCEL", "취소"
        STATUS = "STATUS", "상태 변경"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="사용자",
    )
    action = models.CharField("작업", max_length=10, choices=Action.choices)
    target_table = models.CharField("대상 테이블", max_length=50)
    target_id = models.BigIntegerField("대상 ID")
    summary = models.CharField("대상 설명", max_length=200, blank=True,
                               help_text="기록 당시의 대상 정보 (대상이 나중에 바뀌거나 지워져도 남는다)")
    before = models.JSONField("변경 전", null=True, blank=True)
    after = models.JSONField("변경 후", null=True, blank=True)
    created_at = models.DateTimeField("일시", auto_now_add=True)

    class Meta:
        verbose_name = "작업 이력"
        verbose_name_plural = "작업 이력"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_table", "target_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_action_display()} {self.target_table}#{self.target_id}"

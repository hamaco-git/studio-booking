from django.db import models
from django.db.models import Q


class SmsLog(models.Model):
    """교수에게 보낸(또는 보내려다 건너뛴·실패한) 문자 기록.

    같은 예약·종류·촬영일·모드의 확정/2일 전/당일 문자는 한 번만 성공할 수 있도록
    DB 제약으로 막는다. (타이머가 두 번 돌거나 동시에 실행돼도 중복 발송 없음)
    실패(FAILED)·건너뜀(SKIPPED) 기록은 제약에서 빠지므로 다시 실행하면 재시도된다.
    """

    class Kind(models.TextChoices):
        CONFIRMED = "CONFIRMED", "예약 확정"
        BEFORE_2D = "BEFORE_2D", "촬영 2일 전"
        TODAY = "TODAY", "촬영 당일"
        CHANGED = "CHANGED", "일정 변경"
        CANCELLED = "CANCELLED", "예약 취소"
        TEST = "TEST", "시험 발송"

    # 예약 하나에 한 번만 보내는 종류
    ONCE_KINDS = (Kind.CONFIRMED, Kind.BEFORE_2D, Kind.TODAY)

    class Status(models.TextChoices):
        PENDING = "PENDING", "발송 중"
        SENT = "SENT", "발송 완료"
        FAILED = "FAILED", "실패"
        SKIPPED = "SKIPPED", "건너뜀"

    class Mode(models.TextChoices):
        CONSOLE = "console", "기록만(실제 발송 없음)"
        TEST = "test", "알리고 테스트(실제 발송 없음)"
        LIVE = "live", "실제 발송"

    reservation = models.ForeignKey(
        "booking.Reservation", on_delete=models.CASCADE, null=True, blank=True,
        related_name="sms_logs", verbose_name="예약",
    )
    kind = models.CharField("종류", max_length=10, choices=Kind.choices)
    shoot_date = models.DateField("촬영일", null=True, blank=True)
    mode = models.CharField("모드", max_length=10, choices=Mode.choices)
    receiver = models.CharField("받는 번호", max_length=20, blank=True)
    title = models.CharField("제목", max_length=50, blank=True)
    text = models.TextField("내용")
    status = models.CharField("결과", max_length=10, choices=Status.choices, default=Status.PENDING)
    result_code = models.CharField("결과 코드", max_length=20, blank=True)
    result_message = models.CharField("결과 메시지", max_length=200, blank=True)
    msg_id = models.CharField("알리고 메시지 ID", max_length=50, blank=True)
    created_at = models.DateTimeField("일시", auto_now_add=True)

    class Meta:
        verbose_name = "문자 발송 기록"
        verbose_name_plural = "문자 발송 기록"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "kind", "shoot_date", "mode"],
                condition=Q(status__in=["PENDING", "SENT"], kind__in=["CONFIRMED", "BEFORE_2D", "TODAY"]),
                name="sms_once_per_reservation",
            ),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_kind_display()} {self.receiver} {self.get_status_display()}"

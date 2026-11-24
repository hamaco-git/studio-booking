"""교수 촬영 알림 문자: 예약 확정 즉시, 촬영 2일 전 09:00, 촬영 당일 09:00.

발송 모드(.env SMS_MODE)
  off      아무것도 보내지 않고 기록도 남기지 않음 (기본값)
  console  실제 발송 없이 문자 내용을 기록(관리자 화면·로그)에만 남김 — Mac 테스트용
  test     알리고 API를 테스트 모드(testmode_yn=Y)로 호출 — 키·발신번호·IP 확인용, 실제 발송·과금 없음
  live     실제 발송
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.phone import digits, validate_phone

from . import aligo, messages
from .models import SmsLog

logger = logging.getLogger(__name__)

Kind = SmsLog.Kind
Status = SmsLog.Status


def current_mode():
    return settings.SMS_MODE


def send_text(receiver, title, text, kind, reservation=None, shoot_date=None):
    """문자 1건을 현재 모드로 보내고 SmsLog를 돌려준다. 이미 보낸 문자면 None.

    발송 실패가 예약 처리를 막지 않도록 예외를 던지지 않는다.
    """
    mode = current_mode()
    if mode == "off":
        return None
    log = SmsLog(reservation=reservation, kind=kind, shoot_date=shoot_date, mode=mode,
                 receiver=receiver, title=title[:50], text=text)
    try:
        validate_phone(receiver)
        ok_phone = bool(receiver)
    except Exception:
        ok_phone = False
    if not ok_phone:
        log.status = Status.SKIPPED
        log.result_message = "휴대폰 번호가 없거나 형식이 맞지 않습니다."
        log.save()
        return log
    try:
        with transaction.atomic():
            log.save()  # PENDING 으로 먼저 저장해 중복 발송을 막는다
    except IntegrityError:
        return None
    if mode == "console":
        logger.info("[문자·기록만] %s\n%s", receiver, text)
        log.status = Status.SENT
        log.result_message = "기록만 남김 (실제 발송 안 함)"
    else:
        res = aligo.send(digits(receiver), text, title=title, testmode=(mode == "test"))
        log.status = Status.SENT if res.ok else Status.FAILED
        log.result_code, log.result_message, log.msg_id = res.code, res.message, res.msg_id
    log.save(update_fields=["status", "result_code", "result_message", "msg_id"])
    return log


def notify(reservation, kind, reason="", today=None):
    """예약 한 건에 대한 문자를 보낸다."""
    if current_mode() == "off":
        return None
    try:
        title, text = messages.build(reservation, kind, reason=reason, today=today)
        return send_text(reservation.professor.phone, title, text, kind,
                         reservation=reservation, shoot_date=reservation.date)
    except Exception:  # 문자 문제로 예약 화면이 오류 나면 안 된다
        logger.exception("문자 발송 처리 중 오류 (예약 %s)", reservation.pk)
        return None


def notify_on_commit(reservation, kind, reason=""):
    """DB 저장이 끝난 뒤에 보낸다 (저장이 취소되면 보내지 않음)."""
    if current_mode() == "off":
        return
    transaction.on_commit(lambda: notify(reservation, kind, reason=reason))


REMINDERS = ((Kind.TODAY, 0), (Kind.BEFORE_2D, 2))


def due_reminders(today=None):
    """오늘 보낼 알림 목록 [(종류, 예약)].

    - 당일 알림: 오늘 촬영, 2일 전 알림: 모레 촬영인 확정 예약
    - 오늘 새로 잡힌 예약은 방금 확정 문자를 받았으므로 건너뛴다
    """
    from apps.booking.models import Reservation

    today = today or timezone.localdate()
    out = []
    for kind, days in REMINDERS:
        qs = (Reservation.objects.filter(date=today + timedelta(days=days), status=Reservation.Status.CONFIRMED)
              .select_related("professor", "course", "studio").order_by("start_time", "studio__code"))
        for r in qs:
            if timezone.localdate(r.created_at) == today:
                continue
            out.append((kind, r))
    return out


def already_sent(reservation, kind):
    return SmsLog.objects.filter(
        reservation=reservation, kind=kind, shoot_date=reservation.date, mode=current_mode(),
        status__in=[Status.PENDING, Status.SENT],
    ).exists()

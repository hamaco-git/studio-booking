"""교수에게 보내는 문자 문구.

머리말은 [세계사이버대학] (설정 SMS_ORG_NAME). 내용이 90바이트를 넘으면 장문(LMS)으로 간다.
"""

from django.conf import settings

WEEKDAYS = "월화수목금토일"


def when(r):
    return (f"{r.date.year}년 {r.date.month}월 {r.date.day}일({WEEKDAYS[r.date.weekday()]}) "
            f"{r.start_time:%H:%M}~{r.end_time:%H:%M}")


def where(r):
    s = r.studio
    return f"{s.name} ({s.location})" if s.location else s.name


def details(r):
    return "\n".join([
        f"■ 촬영일시: {when(r)}",
        f"■ 과목: {r.course.name}",
        f"■ 스튜디오: {where(r)}",
    ])


def _footer():
    lines = []
    if settings.SMS_CONTACT:
        lines.append(f"문의: {settings.SMS_CONTACT}")
    return ("\n\n" + "\n".join(lines)) if lines else ""


def _next_notice(r, today):
    days = (r.date - today).days
    if days >= 3:
        return "\n\n촬영 2일 전과 촬영 당일 오전 9시에 다시 안내해 드립니다."
    if days >= 1:
        return "\n\n촬영 당일 오전 9시에 다시 안내해 드립니다."
    return ""


def build(r, kind, reason="", today=None):
    """(제목, 본문)을 돌려준다. kind는 SmsLog.Kind 값."""
    from django.utils import timezone

    today = today or timezone.localdate()
    org = settings.SMS_ORG_NAME
    name = f"{r.professor.name} 교수님"
    if kind == "CONFIRMED":
        title = "스튜디오 촬영 예약 확정"
        body = f"{name}, 스튜디오 촬영 예약이 확정되었습니다.\n\n{details(r)}{_next_notice(r, today)}"
    elif kind == "BEFORE_2D":
        title = "촬영 일정 안내(2일 전)"
        body = (f"{name}, 이틀 뒤 스튜디오 촬영이 예정되어 있습니다.\n\n{details(r)}\n\n"
                "촬영 자료를 미리 준비해 주시기 바랍니다.")
    elif kind == "TODAY":
        title = "오늘은 촬영일입니다"
        body = (f"{name}, 오늘은 스튜디오 촬영일입니다.\n\n{details(r)}\n\n"
                "촬영 시간에 맞춰 스튜디오로 와 주시기 바랍니다.")
    elif kind == "CHANGED":
        title = "촬영 일정 변경 안내"
        body = (f"{name}, 스튜디오 촬영 일정이 아래와 같이 변경되었습니다.\n\n{details(r)}"
                f"{_next_notice(r, today)}")
    elif kind == "CANCELLED":
        title = "촬영 예약 취소 안내"
        body = f"{name}, 아래 스튜디오 촬영 예약이 취소되었습니다.\n\n{details(r)}"
        if reason:
            body += f"\n■ 취소 사유: {reason}"
    else:
        raise ValueError(kind)
    return f"[{org}] {title}", f"[{org}] {title}\n\n{body}{_footer()}"

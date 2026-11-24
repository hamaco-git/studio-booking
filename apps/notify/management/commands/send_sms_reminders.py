"""촬영 2일 전·당일 알림 문자 발송. 서버에서 매일 오전 9시에 systemd 타이머가 실행한다.

  uv run python manage.py send_sms_reminders            # 오늘 기준 발송
  uv run python manage.py send_sms_reminders --dry-run  # 보낼 문자만 화면에 표시 (발송·기록 없음)
  uv run python manage.py send_sms_reminders --date 2027-03-08 --dry-run

이미 보낸 알림은 다시 보내지 않으므로 여러 번 실행해도 안전하다.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.notify import messages, services
from apps.notify.models import SmsLog

# 서버가 꺼져 있다가 늦게 켜진 경우 밤에 문자가 가지 않도록, 이 시간대에만 보낸다.
SEND_FROM_HOUR, SEND_UNTIL_HOUR = 8, 21


class Command(BaseCommand):
    help = "촬영 2일 전·당일 알림 문자를 보낸다 (매일 09:00 실행)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="보낼 문자를 표시만 하고 보내지 않음")
        parser.add_argument("--date", help="이 날짜를 오늘로 보고 계산 (YYYY-MM-DD)")
        parser.add_argument("--force", action="store_true", help="08~21시 밖에서도 발송")

    def handle(self, *args, dry_run=False, date=None, force=False, **opts):
        today = self._parse(date) if date else timezone.localdate()
        mode = services.current_mode()
        now = timezone.localtime()
        if not dry_run:
            if mode == "off":
                self.stdout.write("SMS_MODE=off 입니다. 문자를 보내지 않습니다.")
                return
            if not force and not (SEND_FROM_HOUR <= now.hour < SEND_UNTIL_HOUR):
                self.stdout.write(f"지금({now:%H:%M})은 발송 시간(08~21시)이 아니어서 보내지 않습니다. (--force로 강제)")
                return

        due = services.due_reminders(today)
        counts = {"sent": 0, "skip": 0, "fail": 0, "dup": 0}
        for kind, r in due:
            label = SmsLog.Kind(kind).label
            if dry_run:
                title, text = messages.build(r, kind, today=today)
                sent = " (이미 보냄)" if services.already_sent(r, kind) else ""
                self.stdout.write(f"── {label} · {r.professor.name} {r.professor.phone or '(번호 없음)'}{sent}\n{text}\n")
                continue
            log = services.notify(r, kind, today=today)
            if log is None:
                counts["dup"] += 1
            elif log.status == SmsLog.Status.SENT:
                counts["sent"] += 1
            elif log.status == SmsLog.Status.SKIPPED:
                counts["skip"] += 1
                self.stdout.write(f"건너뜀: {r.professor.name} - {log.result_message}")
            else:
                counts["fail"] += 1
                self.stderr.write(f"실패: {r.professor.name} {log.receiver} - {log.result_code} {log.result_message}")
        if dry_run:
            self.stdout.write(f"{today} 기준 알림 대상 {len(due)}건 (표시만, 발송 안 함)")
        else:
            self.stdout.write(f"{today} [{mode}] 대상 {len(due)}건: 발송 {counts['sent']}, 이미 보냄 {counts['dup']}, "
                              f"번호 없음 {counts['skip']}, 실패 {counts['fail']}")
            if counts["fail"]:
                raise CommandError(f"{counts['fail']}건 발송 실패. 다시 실행하면 실패한 건만 재시도합니다.")

    def _parse(self, value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise CommandError("날짜 형식은 YYYY-MM-DD 입니다.")

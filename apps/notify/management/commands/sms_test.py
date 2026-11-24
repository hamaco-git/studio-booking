"""알리고 설정 확인용 시험 문자 1건 발송.

  uv run python manage.py sms_test 010-1234-5678

SMS_MODE=test 이면 알리고 테스트 모드로 호출(실제 발송·과금 없음)해서
API 키·아이디·발신번호·서버 IP 등록이 맞는지만 확인한다.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.phone import normalize_phone
from apps.notify import services
from apps.notify.models import SmsLog


class Command(BaseCommand):
    help = "시험 문자 1건 발송 (알리고 설정 확인)"

    def add_arguments(self, parser):
        parser.add_argument("phone", help="받을 휴대폰 번호")

    def handle(self, phone, **opts):
        mode = services.current_mode()
        if mode == "off":
            raise CommandError(".env의 SMS_MODE가 off입니다. console / test / live 중 하나로 바꿔 주세요.")
        org = settings.SMS_ORG_NAME
        title = f"[{org}] 문자 발송 시험"
        text = f"[{org}] 스튜디오 예약 시스템 문자 발송 시험입니다."
        log = services.send_text(normalize_phone(phone), title, text, SmsLog.Kind.TEST)
        self.stdout.write(f"모드: {SmsLog.Mode(mode).label}")
        if log.status == SmsLog.Status.SENT:
            self.stdout.write(self.style.SUCCESS(f"성공 {log.result_code} {log.result_message}".strip()))
        else:
            raise CommandError(f"실패: {log.result_code} {log.result_message}")

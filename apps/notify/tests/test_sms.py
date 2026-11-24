import json
from datetime import datetime, time, timedelta
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.booking import services as booking
from apps.booking.models import Reservation
from apps.booking.tests.test_staff import StaffBase
from apps.notify import aligo, messages, services
from apps.notify.models import SmsLog

KST = ZoneInfo("Asia/Seoul")
TODAY = timezone.localdate()
ALIGO = dict(ALIGO_API_KEY="k", ALIGO_USER_ID="u", ALIGO_SENDER="1577-4990")


def at_9am(d):
    return datetime.combine(d, time(9, 0), tzinfo=KST)


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SmsBase(StaffBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.prof.phone = "010-1234-5678"
        cls.prof.save()
        cls.s1.location = "본관 3층"
        cls.s1.save()

    def booked(self, day, created=None):
        r = self.reserve(self.slot(day=day))
        if created:
            Reservation.objects.filter(pk=r.pk).update(created_at=created)
            r.refresh_from_db()
        return r


class MessageTest(SmsBase):
    def test_confirmed_message(self):
        r = self.booked(TODAY + timedelta(days=10))
        title, text = messages.build(r, "CONFIRMED", today=TODAY)
        self.assertEqual(title, "[세계사이버대학] 스튜디오 촬영 예약 확정")
        self.assertTrue(text.startswith("[세계사이버대학]"))
        for part in ["김교수 교수님", "영상제작", "Studio 1 (본관 3층)", "■ 촬영일시:", "2일 전과 촬영 당일"]:
            self.assertIn(part, text)

    def test_confirmed_soon_only_mentions_today_notice(self):
        r = self.booked(TODAY + timedelta(days=1))
        _, text = messages.build(r, "CONFIRMED", today=TODAY)
        self.assertNotIn("2일 전", text)
        self.assertIn("촬영 당일 오전 9시", text)

    def test_today_message(self):
        r = self.booked(TODAY)
        title, text = messages.build(r, "TODAY", today=TODAY)
        self.assertIn("오늘은 촬영일", title)
        self.assertIn("오늘은 스튜디오 촬영일입니다", text)

    @override_settings(SMS_CONTACT="스튜디오 02-111-2222")
    def test_contact_footer(self):
        _, text = messages.build(self.booked(TODAY), "BEFORE_2D", today=TODAY)
        self.assertTrue(text.endswith("문의: 스튜디오 02-111-2222"))

    def test_long_message_goes_lms(self):
        self.assertGreater(aligo.byte_len(messages.build(self.booked(TODAY), "TODAY")[1]), aligo.SMS_MAX_BYTES)


@override_settings(SMS_MODE="console")
class ConfirmOnBookTest(SmsBase):
    def test_booking_sends_confirmation_once(self):
        slot = self.slot(day=TODAY + timedelta(days=7))
        with self.captureOnCommitCallbacks(execute=True):
            r = booking.book_slot(self.prof, self.prof, self.course, slot)
        log = SmsLog.objects.get()
        self.assertEqual((log.reservation, log.kind, log.status, log.receiver), (r, "CONFIRMED", "SENT", "010-1234-5678"))
        self.assertIsNone(services.notify(r, "CONFIRMED"))  # 두 번째는 보내지 않음
        self.assertEqual(SmsLog.objects.count(), 1)

    @override_settings(SMS_MODE="off")
    def test_off_mode_sends_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            booking.book_slot(self.prof, self.prof, self.course, self.slot(day=TODAY + timedelta(days=7)))
        self.assertFalse(SmsLog.objects.exists())

    def test_no_phone_is_skipped(self):
        r = self.reserve(self.slot(day=TODAY + timedelta(days=8)), prof=self.other)
        log = services.notify(r, "CONFIRMED")
        self.assertEqual(log.status, "SKIPPED")

    def test_staff_edit_and_cancel_notify(self):
        r = self.booked(TODAY + timedelta(days=7))
        new = self.slot(day=TODAY + timedelta(days=8))
        self.client.force_login(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(reverse("booking:reservation_edit", args=[r.pk]), {
                "studio": self.s1.pk, "date": new.date.isoformat(),
                "start_time": "09:00", "end_time": "12:00", "memo": ""}, follow=True)
        self.assertContains(res, "변경 안내 문자")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("booking:reservation_cancel", args=[r.pk]), {"reason": "장비 고장"})
        kinds = list(SmsLog.objects.order_by("created_at").values_list("kind", flat=True))
        self.assertEqual(kinds, ["CHANGED", "CANCELLED"])
        self.assertIn("취소 사유: 장비 고장", SmsLog.objects.get(kind="CANCELLED").text)
        self.assertContains(self.client.get(reverse("booking:reservation_edit", args=[r.pk])), "문자 발송 기록")

    def test_memo_only_edit_does_not_notify(self):
        r = self.booked(TODAY + timedelta(days=7))
        self.client.force_login(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("booking:reservation_edit", args=[r.pk]), {
                "studio": self.s1.pk, "date": r.date.isoformat(),
                "start_time": "09:00", "end_time": "12:00", "memo": "메모"})
        self.assertFalse(SmsLog.objects.exists())

    def test_professor_self_cancel_no_sms(self):
        r = self.booked(TODAY + timedelta(days=7))
        self.client.force_login(self.prof)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("booking:my_cancel", args=[r.pk]))
        self.assertEqual(Reservation.objects.get().status, "CANCELLED")
        self.assertFalse(SmsLog.objects.exists())


@override_settings(SMS_MODE="console")
class ReminderTest(SmsBase):
    def run_cmd(self, today, *args):
        out = StringIO()
        with mock.patch("django.utils.timezone.now", return_value=at_9am(today)):
            call_command("send_sms_reminders", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_sends_2day_and_today_once(self):
        old = at_9am(TODAY - timedelta(days=5))
        d2 = self.booked(TODAY + timedelta(days=2), created=old)
        d0 = self.booked(TODAY, created=old)
        self.booked(TODAY + timedelta(days=1), created=old)  # 내일 촬영: 오늘은 보낼 것 없음
        out = self.run_cmd(TODAY)
        self.assertIn("발송 2", out)
        self.assertEqual(set(SmsLog.objects.values_list("reservation_id", "kind")),
                         {(d2.pk, "BEFORE_2D"), (d0.pk, "TODAY")})
        self.assertIn("이미 보냄 2", self.run_cmd(TODAY))  # 다시 실행해도 중복 없음
        self.assertEqual(SmsLog.objects.count(), 2)

    def test_skips_cancelled_and_booked_today(self):
        old = at_9am(TODAY - timedelta(days=5))
        r = self.booked(TODAY + timedelta(days=2), created=old)
        r.status = Reservation.Status.CANCELLED
        r.save()
        self.booked(TODAY, created=at_9am(TODAY) - timedelta(hours=2))  # 오늘 아침 예약 → 확정 문자로 충분
        self.run_cmd(TODAY)
        self.assertFalse(SmsLog.objects.exists())

    def test_dry_run_sends_nothing(self):
        self.booked(TODAY + timedelta(days=2), created=at_9am(TODAY - timedelta(days=5)))
        out = self.run_cmd(TODAY, "--dry-run")
        self.assertIn("이틀 뒤", out)
        self.assertFalse(SmsLog.objects.exists())

    def test_outside_hours_does_not_send(self):
        self.booked(TODAY, created=at_9am(TODAY - timedelta(days=5)))
        out = StringIO()
        night = datetime.combine(TODAY, time(23, 0), tzinfo=KST)
        with mock.patch("django.utils.timezone.now", return_value=night):
            call_command("send_sms_reminders", stdout=out)
        self.assertIn("발송 시간", out.getvalue())
        self.assertFalse(SmsLog.objects.exists())

    def test_date_change_gets_new_reminder(self):
        r = self.booked(TODAY, created=at_9am(TODAY - timedelta(days=5)))
        self.run_cmd(TODAY)
        Reservation.objects.filter(pk=r.pk).update(date=TODAY + timedelta(days=1))
        self.run_cmd(TODAY + timedelta(days=1))
        self.assertEqual(SmsLog.objects.filter(kind="TODAY", status="SENT").count(), 2)


@override_settings(SMS_MODE="test", **ALIGO)
class AligoTest(SmsBase):
    def test_test_mode_calls_aligo_with_testmode(self):
        r = self.booked(TODAY + timedelta(days=5))
        resp = FakeResp({"result_code": "1", "message": "success", "msg_id": "123", "msg_type": "LMS"})
        with mock.patch("urllib.request.urlopen", return_value=resp) as m:
            log = services.notify(r, "CONFIRMED")
        sent = dict(x.split("=", 1) for x in m.call_args.args[0].data.decode().split("&"))
        self.assertEqual((sent["testmode_yn"], sent["msg_type"], sent["receiver"], sent["key"]),
                         ("Y", "LMS", "01012345678", "k"))
        self.assertIn("title", sent)
        self.assertEqual(sent["sender"], "15774990")
        self.assertEqual((log.status, log.msg_id, log.mode), ("SENT", "123", "test"))

    def test_failure_is_recorded_and_retry_allowed(self):
        r = self.booked(TODAY + timedelta(days=5))
        bad = FakeResp({"result_code": "-101", "message": "인증오류입니다."})
        with mock.patch("urllib.request.urlopen", return_value=bad):
            log = services.notify(r, "CONFIRMED")
        self.assertEqual((log.status, log.result_code), ("FAILED", "-101"))
        ok = FakeResp({"result_code": "1", "message": "success", "msg_id": "9"})
        with mock.patch("urllib.request.urlopen", return_value=ok):
            self.assertEqual(services.notify(r, "CONFIRMED").status, "SENT")

    def test_network_error_does_not_break_booking(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                r = booking.book_slot(self.prof, self.prof, self.course, self.slot(day=TODAY + timedelta(days=7)))
        self.assertTrue(Reservation.objects.filter(pk=r.pk).exists())
        self.assertEqual(SmsLog.objects.get().status, "FAILED")

    @override_settings(ALIGO_API_KEY="")
    def test_missing_key(self):
        log = services.notify(self.booked(TODAY + timedelta(days=5)), "CONFIRMED")
        self.assertEqual((log.status, log.result_code), ("FAILED", "CONFIG"))

    def test_sms_test_command(self):
        ok = FakeResp({"result_code": "1", "message": "success", "msg_id": "1"})
        out = StringIO()
        with mock.patch("urllib.request.urlopen", return_value=ok) as m:
            call_command("sms_test", "010 9999 8888", stdout=out)
        self.assertIn("성공", out.getvalue())
        self.assertIn("msg_type=SMS", m.call_args.args[0].data.decode())

    @override_settings(SMS_MODE="off")
    def test_sms_test_off(self):
        with self.assertRaises(CommandError):
            call_command("sms_test", "01099998888")

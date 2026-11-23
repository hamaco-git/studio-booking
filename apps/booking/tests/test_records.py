"""노쇼·취소 기록과 작업 이력."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.booking import services
from apps.booking.models import AuditLog, Reservation

from .test_staff import StaffBase

TODAY = timezone.localdate()


class AttendanceTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def mark(self, r, status, **extra):
        return self.client.post(reverse("booking:reservation_status", args=[r.pk]), {"status": status, **extra})

    def test_mark_no_show_and_completed(self):
        r = self.reserve(self.slot(day=TODAY - timedelta(days=1)))
        self.mark(r, "NO_SHOW")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.NO_SHOW)
        log = AuditLog.objects.get(target_id=r.pk, action=AuditLog.Action.STATUS)
        self.assertEqual(log.user, self.staff)
        self.assertEqual(log.before["status"], "CONFIRMED")
        self.assertEqual(log.after["status"], "NO_SHOW")
        self.assertIn("김교수", log.summary)
        # 잘못 표시했으면 바꾸거나 되돌릴 수 있다
        self.mark(r, "COMPLETED")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.COMPLETED)
        self.mark(r, "CONFIRMED")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CONFIRMED)

    def test_can_mark_on_shoot_day(self):
        r = self.reserve(self.slot(day=TODAY))
        self.mark(r, "COMPLETED")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.COMPLETED)

    def test_cannot_mark_future(self):
        r = self.reserve(self.slot(day=TODAY + timedelta(days=2)))
        res = self.client.post(reverse("booking:reservation_status", args=[r.pk]), {"status": "NO_SHOW"}, follow=True)
        self.assertContains(res, "당일부터")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CONFIRMED)

    def test_cannot_mark_cancelled(self):
        r = self.reserve(self.slot(day=TODAY - timedelta(days=1)))
        services.cancel_reservation(self.staff, r)
        with self.assertRaises(ValidationError):
            services.set_attendance(self.staff, r, Reservation.Status.COMPLETED)

    def test_other_studio_staff_forbidden(self):
        r = self.reserve(self.slot(studio=self.s2, day=TODAY - timedelta(days=1)))
        self.assertEqual(self.mark(r, "NO_SHOW").status_code, 403)

    def test_professor_forbidden(self):
        r = self.reserve(self.slot(day=TODAY - timedelta(days=1)))
        self.client.force_login(self.prof)
        self.assertEqual(self.mark(r, "COMPLETED").status_code, 403)

    def test_no_show_still_blocks_time(self):
        # 노쇼·완료 예약도 시간을 차지한다 (같은 시간에 다른 예약을 넣을 수 없음)
        slot = self.slot(day=TODAY)
        r = self.reserve(slot)
        services.set_attendance(self.staff, r, Reservation.Status.NO_SHOW)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.reserve(slot, prof=self.other)

    def test_list_shows_buttons_and_pending_filter(self):
        past = self.reserve(self.slot(day=TODAY - timedelta(days=2)))
        self.reserve(self.slot(day=TODAY + timedelta(days=2)))
        res = self.client.get(reverse("booking:reservations"),
                              {"start": TODAY - timedelta(days=7), "status": "pending"})
        self.assertContains(res, "처리 전")
        self.assertContains(res, reverse("booking:reservation_status", args=[past.pk]))
        self.assertEqual(len(res.context["rows"]), 1)

    def test_status_filter(self):
        r = self.reserve(self.slot(day=TODAY - timedelta(days=2)))
        services.set_attendance(self.staff, r, Reservation.Status.NO_SHOW)
        url = reverse("booking:reservations")
        start = TODAY - timedelta(days=7)
        self.assertEqual(len(self.client.get(url, {"start": start, "status": "NO_SHOW"}).context["rows"]), 1)
        self.assertEqual(len(self.client.get(url, {"start": start, "status": "COMPLETED"}).context["rows"]), 0)
        # 기본(취소 제외 전체)에는 노쇼도 보인다
        self.assertEqual(len(self.client.get(url, {"start": start}).context["rows"]), 1)


class CancelRecordTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_staff_cancel_keeps_record_with_reason(self):
        r = self.reserve(self.slot(day=TODAY + timedelta(days=1)))
        self.client.post(reverse("booking:reservation_cancel", args=[r.pk]), {"reason": "장비 고장"})
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CANCELLED)
        self.assertEqual(r.cancel_reason, "장비 고장")
        self.assertEqual(r.cancelled_by, self.staff)
        self.assertTrue(Reservation.objects.filter(pk=r.pk).exists())
        log = AuditLog.objects.get(target_id=r.pk, action=AuditLog.Action.CANCEL)
        self.assertEqual(log.after["cancel_reason"], "장비 고장")

    def test_cannot_cancel_completed(self):
        r = self.reserve(self.slot(day=TODAY))
        services.set_attendance(self.staff, r, Reservation.Status.COMPLETED)
        res = self.client.post(reverse("booking:reservation_cancel", args=[r.pk]), follow=True)
        self.assertContains(res, "취소할 수 없습니다")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.COMPLETED)

    def test_cancelled_slot_can_be_booked_again(self):
        slot = self.slot(day=TODAY + timedelta(days=3))
        services.cancel_reservation(self.staff, self.reserve(slot))
        self.reserve(slot, prof=self.other)  # 오류 없이 예약됨

    def test_records_page(self):
        a = self.reserve(self.slot(day=TODAY - timedelta(days=3)))
        b = self.reserve(self.slot(day=TODAY - timedelta(days=2)))
        c = self.reserve(self.slot(day=TODAY - timedelta(days=1)))
        self.reserve(self.slot(day=TODAY - timedelta(days=1), tpl=self.pm))  # 처리 전
        services.set_attendance(self.staff, a, Reservation.Status.NO_SHOW)
        services.set_attendance(self.staff, b, Reservation.Status.COMPLETED)
        services.cancel_reservation(self.staff, c, reason="교수 요청")
        res = self.client.get(reverse("booking:records"), {"start": TODAY - timedelta(days=10), "end": TODAY})
        self.assertEqual(res.status_code, 200)
        row = res.context["summary"][0]
        self.assertEqual((row["total"], row["completed"], row["no_show"], row["cancelled"], row["pending"]),
                         (4, 1, 1, 1, 1))
        self.assertEqual(row["cancelled_by_staff"], 1)
        self.assertContains(res, "교수 요청")
        self.assertContains(res, "처리 전 1건")

    def test_records_forbidden_for_professor(self):
        self.client.force_login(self.prof)
        self.assertEqual(self.client.get(reverse("booking:records")).status_code, 403)

    def test_edit_page_shows_history_and_phone(self):
        self.prof.phone = "010-1234-5678"
        self.prof.save()
        r = self.reserve(self.slot(day=TODAY))
        services.set_attendance(self.staff, r, Reservation.Status.NO_SHOW)
        res = self.client.get(reverse("booking:reservation_edit", args=[r.pk]))
        self.assertContains(res, "010-1234-5678")
        self.assertContains(res, "상태 변경")
        self.assertContains(res, "확정 → 불참(노쇼)")
        # 완료·노쇼 예약은 시간 수정 폼이 없다
        self.assertIsNone(res.context["form"])

    def test_calendar_marks_no_show_for_staff_only(self):
        r = self.reserve(self.slot(day=TODAY))
        services.set_attendance(self.staff, r, Reservation.Status.NO_SHOW)
        data = self.client.get(reverse("booking:events"), {"start": TODAY, "end": TODAY + timedelta(days=1)}).json()
        self.assertTrue(any(e["title"].startswith("[노쇼]") for e in data))
        self.client.force_login(self.other)
        self.course.professors.add(self.other)
        data = self.client.get(reverse("booking:events"), {"start": TODAY, "end": TODAY + timedelta(days=1)}).json()
        titles = [e["title"] for e in data if e["extendedProps"]["kind"] == "reservation"]
        self.assertEqual(titles, ["studio1 예약됨"])


class WorkLogTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_logs_filter_by_action_and_target(self):
        r = self.reserve(self.slot(day=TODAY))
        services.set_attendance(self.staff, r, Reservation.Status.NO_SHOW)
        other = self.reserve(self.slot(day=TODAY, tpl=self.pm), prof=self.other)
        services.cancel_reservation(self.staff, other)
        res = self.client.get(reverse("manage:logs"), {"action": "STATUS"})
        self.assertEqual(len(res.context["rows"]), 1)
        self.assertContains(res, "상태 변경")
        self.assertContains(res, "확정 → 불참(노쇼)")
        self.assertContains(res, reverse("booking:reservation_edit", args=[r.pk]))
        res = self.client.get(reverse("manage:logs"), {"target": "이교수"})
        self.assertEqual([row[0].action for row in res.context["rows"]], ["CANCEL"])

    def test_book_logs_create_with_summary(self):
        slot = self.slot(day=TODAY + timedelta(days=5))
        r = services.book_slot(self.staff, self.prof, self.course, slot)
        log = AuditLog.objects.get(target_id=r.pk, target_table="booking_reservation", action="CREATE")
        self.assertIn(self.course.name, log.summary)
        self.assertEqual(log.user, self.staff)

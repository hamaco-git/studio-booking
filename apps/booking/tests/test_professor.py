from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.booking.models import AuditLog, Blackout, Reservation
from apps.studios.models import Course, CourseProfessor

from .test_staff import StaffBase

TODAY = timezone.localdate()


class ProfessorBookingTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.prof)
        self.future = TODAY + timedelta(days=7)

    def reserve_post(self, slot, course=None, **extra):
        return self.client.post(reverse("booking:reserve"),
                                {"course": (course or self.course).pk, "slot": slot.pk, **extra}, follow=True)

    def test_home_goes_to_book(self):
        self.assertRedirects(self.client.get(reverse("home")), reverse("booking:book"))

    def test_book_page_shows_assigned_course(self):
        res = self.client.get(reverse("booking:book"))
        self.assertContains(res, "영상제작 · Studio 1")

    def test_book_page_without_course(self):
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse("booking:book")), "배정된 과목이 없습니다")

    def test_reserve_free_slot(self):
        s = self.slot(day=self.future)
        res = self.reserve_post(s, memo="3주차")
        self.assertContains(res, "예약했습니다")
        r = Reservation.objects.get()
        self.assertEqual((r.professor, r.slot, r.memo, r.created_by), (self.prof, s, "3주차", self.prof))
        self.assertTrue(AuditLog.objects.filter(target_table="booking_reservation", action="CREATE").exists())

    def test_cannot_reserve_taken_slot(self):
        s = self.slot(day=self.future)
        self.reserve(s, prof=self.prof)
        res = self.reserve_post(s)
        self.assertContains(res, "이미 예약된 시간")
        self.assertEqual(Reservation.objects.count(), 1)

    def test_cannot_reserve_past_slot(self):
        res = self.reserve_post(self.slot(day=TODAY - timedelta(days=1)))
        self.assertContains(res, "지난 날짜")
        self.assertFalse(Reservation.objects.exists())

    def test_cannot_reserve_other_studio(self):
        res = self.reserve_post(self.slot(studio=self.s2, day=self.future))
        self.assertContains(res, "지정된 스튜디오")
        self.assertFalse(Reservation.objects.exists())

    def test_cannot_use_course_of_other_professor(self):
        c2 = Course.objects.create(semester=self.course.semester, code="C2", name="남의과목", studio=self.s1)
        CourseProfessor.objects.create(course=c2, professor=self.other)
        res = self.reserve_post(self.slot(day=self.future), course=c2)
        self.assertContains(res, "다시 선택")
        self.assertFalse(Reservation.objects.exists())

    def test_cannot_reserve_blackout(self):
        s = self.slot(day=self.future)
        Blackout.objects.create(studio=self.s1, date=self.future)
        self.assertContains(self.reserve_post(s), "촬영 불가일")

    def test_race_condition_reports_friendly_message(self):
        s = self.slot(day=self.future)
        # 검사 통과 직후 다른 사람이 먼저 저장한 상황을 흉내 낸다
        with mock.patch.object(Reservation, "full_clean"):
            self.reserve(s, prof=self.prof)
            res = self.reserve_post(s)
        self.assertContains(res, "먼저 예약했습니다")

    def test_staff_pages_forbidden(self):
        self.assertEqual(self.client.get(reverse("booking:reservations")).status_code, 403)


class ProfessorCancelTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.prof)

    def test_cancel_before_deadline(self):
        r = self.reserve(self.slot(day=TODAY + timedelta(days=2)))
        res = self.client.post(reverse("booking:my_cancel", args=[r.pk]), follow=True)
        self.assertContains(res, "취소했습니다")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CANCELLED)

    def test_cancel_after_deadline_refused(self):
        r = self.reserve(self.slot(day=TODAY + timedelta(days=1)))
        res = self.client.post(reverse("booking:my_cancel", args=[r.pk]), follow=True)
        self.assertContains(res, "담당자에게 문의")
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CONFIRMED)

    def test_cannot_cancel_others_reservation(self):
        r = self.reserve(self.slot(day=TODAY + timedelta(days=5)))
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse("booking:my_cancel", args=[r.pk])).status_code, 404)

    def test_my_reservations_lists_upcoming_and_past(self):
        self.reserve(self.slot(day=TODAY + timedelta(days=5)))
        self.reserve(self.slot(day=TODAY - timedelta(days=5)))
        res = self.client.get(reverse("booking:my_reservations"))
        self.assertContains(res, "까지 가능")
        self.assertContains(res, "촬영 완료")


class StaffProxyBookingTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)
        self.future = TODAY + timedelta(days=3)

    def test_proxy_booking(self):
        s = self.slot(day=self.future)
        pair = CourseProfessor.objects.get(course=self.course, professor=self.prof)
        page = self.client.get(reverse("booking:reservation_new"), {"slot": s.pk})
        self.assertContains(page, "영상제작 · 김교수")
        res = self.client.post(reverse("booking:reservation_new"), {"slot": s.pk, "pair": pair.pk})
        self.assertRedirects(res, reverse("booking:calendar"))
        r = Reservation.objects.get()
        self.assertEqual((r.professor, r.created_by), (self.prof, self.staff))

    def test_proxy_booking_other_studio_forbidden(self):
        s = self.slot(studio=self.s2, day=self.future)
        self.assertEqual(self.client.get(reverse("booking:reservation_new"), {"slot": s.pk}).status_code, 403)


class CalendarAvailabilityTest(StaffBase):
    def events(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("booking:events"),
                               {"start": TODAY - timedelta(days=3), "end": TODAY + timedelta(days=10)}).json()

    def slot_ids(self, events):
        return {e["extendedProps"]["id"] for e in events if e["extendedProps"]["kind"] == "slot"}

    def test_blocked_or_taken_slots_not_offered(self):
        free = self.slot(day=TODAY + timedelta(days=2))
        blocked = self.slot(day=TODAY + timedelta(days=3))
        Blackout.objects.create(studio=self.s1, date=blocked.date)
        taken = self.slot(day=TODAY + timedelta(days=4))
        self.reserve(taken)
        # 담당자가 시간을 옮겨 슬롯 연결 없이 걸친 예약
        partly = self.slot(day=TODAY + timedelta(days=5))
        r = self.reserve(partly)
        Reservation.objects.filter(pk=r.pk).update(slot=None)
        self.assertEqual(self.slot_ids(self.events(self.prof)), {free.pk})

    def test_past_slots_hidden_from_professor_only(self):
        past = self.slot(day=TODAY - timedelta(days=1))
        self.assertNotIn(past.pk, self.slot_ids(self.events(self.prof)))
        self.assertIn(past.pk, self.slot_ids(self.events(self.staff)))


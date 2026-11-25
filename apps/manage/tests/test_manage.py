import csv
import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.booking.models import AuditLog
from apps.booking.tests.test_staff import StaffBase
from apps.manage import services
from apps.studios.models import Course, Semester


class CourseManageTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)
        self.sem = self.course.semester

    def post_course(self, pk=None, **data):
        url = reverse("manage:course_edit", args=[pk]) if pk else reverse("manage:course_new")
        base = {"semester": self.sem.pk, "code": "C9", "name": "새과목", "studio": self.s1.pk,
                "professors": [self.prof.pk, self.other.pk], "is_active": "on"}
        base.update(data)
        return self.client.post(url, base)

    def test_create_course_with_professors(self):
        res = self.post_course()
        self.assertEqual(res.status_code, 302)
        c = Course.objects.get(code="C9")
        self.assertEqual(set(c.professors.all()), {self.prof, self.other})
        self.assertTrue(AuditLog.objects.filter(target_table="studios_course", action="CREATE").exists())

    def test_duplicate_code_message(self):
        res = self.post_course(code="C1")
        self.assertContains(res, "같은 과목 코드가 이미 있습니다")

    def test_staff_cannot_use_other_studio(self):
        res = self.post_course(studio=self.s2.pk)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Course.objects.filter(code="C9").exists())

    def test_staff_cannot_edit_other_studio_course(self):
        c = Course.objects.create(semester=self.sem, code="X", name="남", studio=self.s2)
        self.assertEqual(self.client.get(reverse("manage:course_edit", args=[c.pk])).status_code, 403)

    def test_edit_reassigns_professors(self):
        self.post_course(pk=self.course.pk, code="C1", name="영상제작", professors=[self.other.pk])
        self.assertEqual(list(self.course.professors.all()), [self.other])

    def test_list(self):
        res = self.client.get(reverse("manage:courses"), {"semester": self.sem.pk})
        self.assertContains(res, "영상제작")
        self.assertContains(res, "김교수")

    def test_professor_forbidden(self):
        self.client.force_login(self.prof)
        self.assertEqual(self.client.get(reverse("manage:courses")).status_code, 403)


class SemesterTest(StaffBase):
    def test_create_current_semester_replaces_previous(self):
        self.client.force_login(self.staff)
        Semester.objects.update(is_current=True)
        self.client.post(reverse("manage:semesters"), {
            "name": "2027-2", "start_date": "2027-09-01", "end_date": "2027-12-31", "make_current": "on"})
        self.assertEqual(list(Semester.objects.filter(is_current=True).values_list("name", flat=True)), ["2027-2"])


class UserManageTest(StaffBase):
    def test_staff_creates_professor_with_temp_password(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_new"), {
            "username": "Park", "name": "박교수", "phone": "", "role": "SUPER", "is_active": "on"},
            follow=True)
        u = User.objects.get(username="park")
        self.assertEqual(u.role, User.Role.PROFESSOR)  # 담당자는 역할을 정할 수 없다
        self.assertTrue(u.must_change_password)
        self.assertContains(res, "임시 비밀번호 wcu-")

    def test_staff_cannot_edit_staff_or_super(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("manage:user_edit", args=[self.admin.pk])).status_code, 404)

    def test_super_can_create_staff(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("manage:user_new"), {
            "username": "staff9", "name": "담당9", "role": "STAFF", "is_active": "on"})
        self.assertEqual(User.objects.get(username="staff9").role, User.Role.STAFF)

    def test_duplicate_username(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_new"), {"username": "KIM", "name": "중복"})
        self.assertContains(res, "이미 등록된 아이디")

    def test_email_style_username_rejected(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_new"), {"username": "choi@wcu.ac.kr", "name": "최교수"})
        self.assertContains(res, "@를 쓸 수 없습니다")
        self.assertFalse(User.objects.filter(name="최교수").exists())

    def test_reset_password(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_reset_password", args=[self.prof.pk]), follow=True)
        self.assertContains(res, "임시 비밀번호: wcu-")
        self.prof.refresh_from_db()
        self.assertTrue(self.prof.must_change_password)
        self.assertFalse(self.prof.check_password("x"))

    def test_deactivate(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("manage:user_edit", args=[self.prof.pk]), {
            "username": self.prof.username, "name": self.prof.name, "phone": ""})
        self.prof.refresh_from_db()
        self.assertFalse(self.prof.is_active)

    def test_phone_saved_normalized_and_searchable(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_edit", args=[self.prof.pk]),
                               {"username": self.prof.username, "name": self.prof.name, "phone": "01055556666",
                                "is_active": "on"})
        self.assertEqual(res.status_code, 302)
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.phone, "010-5555-6666")
        res = self.client.get(reverse("manage:users"), {"q": "55556666"})
        self.assertContains(res, "010-5555-6666")
        res = self.client.get(reverse("manage:users"), {"nophone": "1"})
        self.assertNotContains(res, "010-5555-6666")
        self.assertContains(res, self.other.name)

    def test_invalid_phone_rejected(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_edit", args=[self.prof.pk]),
                               {"username": self.prof.username, "name": self.prof.name, "phone": "12345",
                                "is_active": "on"})
        self.assertContains(res, "휴대폰 번호 형식")

    def test_list_hides_staff_for_staff(self):
        self.client.force_login(self.staff)
        res = self.client.get(reverse("manage:users"))
        self.assertContains(res, "김교수")
        self.assertNotContains(res, "관리자")


class ImportTest(StaffBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def upload(self, text, encoding="utf-8", semester=True):
        f = SimpleUploadedFile("p.csv", text.encode(encoding), content_type="text/csv")
        data = {"file": f}
        if semester:
            data["semester"] = self.course.semester.pk
        return self.client.post(reverse("manage:users_import"), data)

    def test_import_creates_and_assigns(self):
        res = self.upload("이메일,이름,연락처,과목코드\nnew1,새교수1,,C1\nkim,,,C1\nbad@wcu.ac.kr,x,,\n")
        self.assertContains(res, "새 계정 1개, 오류 1건")
        u = User.objects.get(username="new1")
        self.assertTrue(u.must_change_password)
        self.assertIn(u, self.course.professors.all())
        # 결과 CSV는 한 번만 내려받을 수 있다
        out = self.client.get(reverse("manage:users_import_result")).content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[1][3], "생성")
        self.assertTrue(rows[1][4].startswith("wcu-"))
        self.assertEqual(rows[2][3], "기존 계정")
        self.assertEqual(self.client.get(reverse("manage:users_import_result")).status_code, 302)

    def test_import_cp949_from_excel(self):
        self.upload("이메일,이름\ncp,엑셀교수\n", encoding="cp949")
        self.assertEqual(User.objects.get(username="cp").name, "엑셀교수")

    def test_unknown_course_code_creates_account_with_warning(self):
        res = self.upload("new2,새교수2,,NOPE;C1\n")
        self.assertContains(res, "새 계정 1개, 오류 0건. 경고 1건")
        self.assertContains(res, "아직 없는 과목코드라 배정 건너뜀: NOPE")
        self.assertContains(res, "table-warning")
        u = User.objects.get(username="new2")
        self.assertEqual(list(u.courses.all()), [self.course])  # 있는 과목은 배정

    def test_codes_without_semester_creates_account_with_warning(self):
        res = self.upload("new4,새교수4,,C1\n", semester=False)
        self.assertContains(res, "기준 학기를 고르지 않아")
        self.assertFalse(User.objects.get(username="new4").courses.exists())

    def test_import_phone_normalized_and_validated(self):
        res = self.upload("이메일,이름,휴대폰 번호,과목코드\n"
                          "ph1,폰교수,01011112222,\n"
                          "ph2,잘못된번호,02-123-4567,\n")
        self.assertContains(res, "새 계정 1개, 오류 1건")
        self.assertEqual(User.objects.get(username="ph1").phone, "010-1111-2222")
        self.assertFalse(User.objects.filter(username="ph2").exists())
        self.assertContains(res, "휴대폰 번호 형식")

    def test_import_updates_phone_of_existing_account(self):
        self.upload("kim,,010 3333 4444,C1\n")
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.phone, "010-3333-4444")
        log = AuditLog.objects.filter(target_table="accounts_user", target_id=self.prof.pk).latest("created_at")
        self.assertEqual(log.after["phone"], "010-3333-4444")

    def test_import_old_header_still_works(self):
        res = self.upload("이메일,이름,연락처,과목코드\nold,옛양식,,\n")
        self.assertContains(res, "새 계정 1개, 오류 0건")

    def test_template_download(self):
        res = self.client.get(reverse("manage:users_import_template"))
        text = res.content.decode("utf-8-sig")
        self.assertIn("아이디", text)
        self.assertNotIn("@", text)

    def test_import_rejects_email_style_id(self):
        res = self.upload("아이디,이름\nnew3@wcu.ac.kr,메일교수\n")
        self.assertContains(res, "새 계정 0개, 오류 1건")
        self.assertContains(res, "@를 쓸 수 없습니다")
        self.assertFalse(User.objects.filter(username__startswith="new3").exists())

    def test_temp_password_format(self):
        self.assertRegex(services.temp_password(), r"^wcu-\d{4}-[a-z]{4}$")


class CourseImportTest(StaffBase):
    HEAD = "학기,과목코드,과목명,스튜디오,담당 교수 아이디,교수설계자 아이디,사용 여부\n"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.designer = User.objects.create_user("des1", password="x", name="설계자",
                                                role=User.Role.DESIGNER, must_change_password=False)

    def setUp(self):
        self.client.force_login(self.staff)

    def preview(self, text, encoding="utf-8", semester=True):
        f = SimpleUploadedFile("c.csv", (self.HEAD + text).encode(encoding), content_type="text/csv")
        data = {"file": f, "step": "preview"}
        if semester:
            data["semester"] = self.course.semester.pk
        return self.client.post(reverse("manage:courses_import"), data)

    def apply(self):
        return self.client.post(reverse("manage:courses_import"), {"step": "apply"}, follow=True)

    def test_preview_does_not_save_then_apply_creates(self):
        res = self.preview("2027-1,C2,새과목,studio1,kim;LEE,des1,\n")
        self.assertContains(res, "미리보기")
        self.assertContains(res, "신규 1")
        self.assertFalse(Course.objects.filter(code="C2").exists())
        res = self.apply()
        self.assertContains(res, "과목 1개를 저장했습니다")
        c = Course.objects.get(code="C2")
        self.assertEqual(c.studio, self.s1)
        self.assertEqual(set(c.professors.all()), {self.prof, self.other})
        self.assertEqual(c.designer, self.designer)
        self.assertTrue(c.is_active)
        self.assertTrue(AuditLog.objects.filter(target_table="studios_course", target_id=c.pk,
                                                action="CREATE").exists())
        # 같은 미리보기를 두 번 저장할 수 없다
        self.assertContains(self.apply(), "미리보기가 만료")

    def test_update_keeps_blank_fields_and_replaces_professors(self):
        self.course.designer = self.designer
        self.course.save()
        self.preview(",C1,영상제작 개정,Studio 1,lee,,\n")  # 학기 칸이 비면 선택한 학기
        self.apply()
        self.course.refresh_from_db()
        self.assertEqual(self.course.name, "영상제작 개정")
        self.assertEqual(list(self.course.professors.all()), [self.other])
        self.assertEqual(self.course.designer, self.designer)  # 빈 칸은 그대로

    def test_dash_clears_designer_and_stop(self):
        self.course.designer = self.designer
        self.course.save()
        res = self.preview("2027-1,C1,,,,-,중지\n")
        self.assertContains(res, "갱신 1")
        self.apply()
        self.course.refresh_from_db()
        self.assertIsNone(self.course.designer)
        self.assertFalse(self.course.is_active)
        self.assertEqual(list(self.course.professors.all()), [self.prof])

    def test_unchanged_row(self):
        res = self.preview("2027-1,C1,영상제작,studio1,kim,,사용\n")
        self.assertContains(res, "변경 없음 1")
        self.assertContains(res, "저장할 행이 없습니다")

    def test_errors_reported_and_skipped(self):
        res = self.preview(
            "2099-9,X1,과목,studio1,,,\n"        # 없는 학기
            "2027-1,X2,과목,studio9,,,\n"        # 없는 스튜디오
            "2027-1,X3,과목,studio2,,,\n"        # 담당이 아닌 스튜디오
            "2027-1,X7,,studio1,,,\n"            # 과목명 없음
            "2027-1,X8,과목,studio1,,,몰라\n"     # 사용 여부 오류
            "2027-1,OK,정상,studio1,kim,,\n"
            "2027-1,OK,중복,studio1,,,\n")       # 파일 안 중복
        self.assertContains(res, "오류 6")
        for msg in ["등록되지 않은 학기", "없는 스튜디오", "담당 스튜디오가 아닙니다",
                    "과목명이 필요", "사용 여부는",
                    "같은 학기·과목코드"]:
            self.assertContains(res, msg)
        self.apply()
        self.assertEqual(list(Course.objects.filter(code__startswith="X")), [])
        self.assertEqual(Course.objects.get(code="OK").name, "정상")

    def test_unknown_people_are_warnings_and_course_is_saved(self):
        res = self.preview(
            "2027-1,X4,과목4,studio1,nobody;kim,,\n"  # 없는 교수 → 있는 교수만 배정
            "2027-1,X5,과목5,studio1,staff1,,\n"      # 교수가 아님
            "2027-1,X6,과목6,studio1,,kim,\n"         # 교수설계자가 아님
            "2027-1,X9,과목9,studio1,,어복희,\n")     # 없는 교수설계자
        self.assertContains(res, "신규 4")
        self.assertContains(res, "경고 4")
        for msg in ["아직 없는 교수 아이디라 배정 건너뜀: nobody", "교수 계정이 아니라 배정 건너뜀: staff1",
                    "교수설계자 계정이 아니라 건너뜀: kim", "없는 교수설계자라 건너뜀: 어복희"]:
            self.assertContains(res, msg)
        self.apply()
        self.assertEqual(list(Course.objects.get(code="X4").professors.all()), [self.prof])
        self.assertIsNone(Course.objects.get(code="X6").designer)

    def test_designer_matched_by_name(self):
        res = self.preview("2027-1,C1,,,,설계자,\n")
        self.assertContains(res, "갱신 1")
        self.apply()
        self.course.refresh_from_db()
        self.assertEqual(self.course.designer, self.designer)

    def test_partial_professors_do_not_remove_existing(self):
        self.preview("2027-1,C1,,,lee;nobody,,\n")
        self.apply()
        self.assertEqual(set(self.course.professors.all()), {self.prof, self.other})

    def test_courses_first_then_professors_fills_assignment(self):
        self.preview("2027-1,N1,새과목,studio1,newprof,,\n")
        self.apply()
        c = Course.objects.get(code="N1")
        self.assertFalse(c.professors.exists())
        f = SimpleUploadedFile("p.csv", "아이디,이름,휴대폰 번호,과목코드\nnewprof,새교수,,N1\n".encode(),
                               content_type="text/csv")
        res = self.client.post(reverse("manage:users_import"), {"file": f, "semester": c.semester.pk})
        self.assertContains(res, "새 계정 1개, 오류 0건.")
        self.assertEqual([u.username for u in c.professors.all()], ["newprof"])

    def test_professors_first_then_courses_fills_assignment(self):
        f = SimpleUploadedFile("p.csv", "아이디,이름,휴대폰 번호,과목코드\nnewprof,새교수,,N1\n".encode(),
                               content_type="text/csv")
        res = self.client.post(reverse("manage:users_import"), {"file": f, "semester": self.course.semester.pk})
        self.assertContains(res, "경고 1건")
        self.preview("2027-1,N1,새과목,studio1,newprof,,\n")
        self.apply()
        self.assertEqual([u.username for u in Course.objects.get(code="N1").professors.all()], ["newprof"])

    def test_staff_cannot_update_other_studio_course(self):
        Course.objects.create(semester=self.course.semester, code="S2", name="남의과목", studio=self.s2)
        res = self.preview("2027-1,S2,바꾸기,,,,\n")
        self.assertContains(res, "담당 스튜디오가 아닌 과목")

    def test_super_admin_any_studio_and_cp949(self):
        self.client.force_login(self.admin)
        self.preview("2027-1,C3,엑셀과목,studio2,,,\n", encoding="cp949")
        self.apply()
        self.assertEqual(Course.objects.get(code="C3").studio, self.s2)

    def test_template_and_export(self):
        text = self.client.get(reverse("manage:courses_import_template")).content.decode("utf-8-sig")
        self.assertTrue(text.startswith("학기,과목코드"))
        out = self.client.get(reverse("manage:courses_export"),
                              {"semester": self.course.semester.pk}).content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[1], ["2027-1", "C1", "영상제작", "studio1", "kim", "", "사용"])
        # 내려받은 파일을 그대로 올리면 변경 없음
        f = SimpleUploadedFile("c.csv", out.encode("utf-8-sig"), content_type="text/csv")
        res = self.client.post(reverse("manage:courses_import"), {"file": f, "step": "preview"})
        self.assertContains(res, "변경 없음 1")

    def test_menu_and_entry_from_courses(self):
        res = self.client.get(reverse("manage:courses"))
        self.assertContains(res, reverse("manage:courses_import"))
        res = self.client.get(reverse("manage:courses_import"))
        self.assertContains(res, "일괄 등록")
        self.assertContains(res, "교수 일괄 등록")
        self.assertContains(res, "과목 일괄 등록")

    def test_professor_forbidden(self):
        self.client.force_login(self.prof)
        self.assertEqual(self.client.get(reverse("manage:courses_import")).status_code, 403)


class ExportAndLogsTest(StaffBase):
    def test_excel_export(self):
        self.client.force_login(self.staff)
        day = timezone.localdate() + timedelta(days=3)
        self.reserve(self.slot(day=day))
        res = self.client.get(reverse("booking:reservations_export"), {"start": day, "end": day})
        self.assertEqual(res["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        ws = load_workbook(io.BytesIO(res.content)).active
        self.assertEqual(ws["A1"].value, "날짜")
        self.assertEqual(ws["F2"].value, "김교수")
        self.assertEqual(ws["A2"].value.date(), day)
        self.assertIsNone(ws["A3"].value)

    def test_logs_page(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("manage:user_reset_password", args=[self.prof.pk]))
        res = self.client.get(reverse("manage:logs"), {"table": "accounts_user"})
        self.assertContains(res, "계정 #")
        self.assertContains(res, "초기화")


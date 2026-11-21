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
            "username": "Park@WCU.ac.kr", "name": "박교수", "phone": "", "role": "SUPER", "is_active": "on"},
            follow=True)
        u = User.objects.get(username="park@wcu.ac.kr")
        self.assertEqual(u.role, User.Role.PROFESSOR)  # 담당자는 역할을 정할 수 없다
        self.assertTrue(u.must_change_password)
        self.assertContains(res, "임시 비밀번호 wcu-")

    def test_staff_cannot_edit_staff_or_super(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("manage:user_edit", args=[self.admin.pk])).status_code, 404)

    def test_super_can_create_staff(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("manage:user_new"), {
            "username": "staff9@wcu.ac.kr", "name": "담당9", "role": "STAFF", "is_active": "on"})
        self.assertEqual(User.objects.get(username="staff9@wcu.ac.kr").role, User.Role.STAFF)

    def test_duplicate_username(self):
        self.client.force_login(self.staff)
        res = self.client.post(reverse("manage:user_new"), {"username": "KIM@wcu.ac.kr", "name": "중복"})
        self.assertContains(res, "이미 등록된 아이디")

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
        res = self.upload("이메일,이름,연락처,과목코드\nnew1@wcu.ac.kr,새교수1,,C1\nkim@wcu.ac.kr,,,C1\nbad,x,,\n")
        self.assertContains(res, "새 계정 1개, 오류 1건")
        u = User.objects.get(username="new1@wcu.ac.kr")
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
        self.upload("이메일,이름\ncp@wcu.ac.kr,엑셀교수\n", encoding="cp949")
        self.assertEqual(User.objects.get(username="cp@wcu.ac.kr").name, "엑셀교수")

    def test_unknown_course_code_is_error(self):
        res = self.upload("new2@wcu.ac.kr,새교수2,,NOPE\n")
        self.assertContains(res, "없는 과목코드")
        self.assertFalse(User.objects.filter(username="new2@wcu.ac.kr").exists())

    def test_template_download(self):
        res = self.client.get(reverse("manage:users_import_template"))
        self.assertIn("이메일", res.content.decode("utf-8-sig"))

    def test_temp_password_format(self):
        self.assertRegex(services.temp_password(), r"^wcu-\d{4}-[a-z]{4}$")


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


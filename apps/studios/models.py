from django.conf import settings
from django.db import models
from django.db.models import Q


class Studio(models.Model):
    """촬영 스튜디오 (studio1 ~ studio4)."""

    code = models.SlugField("코드", max_length=20, unique=True)
    name = models.CharField("이름", max_length=50)
    location = models.CharField("위치", max_length=100, blank=True)
    color = models.CharField("달력 색상", max_length=7, default="#4f7cff", help_text="예: #4f7cff")
    is_active = models.BooleanField("사용 중", default=True)
    staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="StudioStaff",
        related_name="managed_studios",
        verbose_name="담당자",
        blank=True,
    )

    class Meta:
        verbose_name = "스튜디오"
        verbose_name_plural = "스튜디오"
        ordering = ["code"]

    def __str__(self):
        return self.name


class StudioStaff(models.Model):
    """담당자와 스튜디오 연결. 담당자는 연결된 스튜디오만 수정할 수 있다."""

    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, verbose_name="스튜디오")
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "STAFF"},
        verbose_name="담당자",
    )

    class Meta:
        verbose_name = "스튜디오 담당자"
        verbose_name_plural = "스튜디오 담당자"
        constraints = [
            models.UniqueConstraint(fields=["studio", "staff"], name="uniq_studio_staff"),
        ]

    def __str__(self):
        return f"{self.studio} - {self.staff.name}"


class Semester(models.Model):
    """학기. 과목과 스튜디오 배정은 학기마다 새로 등록한다."""

    name = models.CharField("학기", max_length=20, unique=True, help_text="예: 2027-1")
    start_date = models.DateField("시작일")
    end_date = models.DateField("종료일")
    is_current = models.BooleanField("현재 학기", default=False)

    class Meta:
        verbose_name = "학기"
        verbose_name_plural = "학기"
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")), name="semester_dates_valid"
            ),
            models.UniqueConstraint(
                fields=["is_current"], condition=Q(is_current=True), name="one_current_semester"
            ),
        ]

    def __str__(self):
        return self.name


class Course(models.Model):
    """과목. 과목마다 지정 스튜디오가 하나 있고, 담당 교수설계자를 한 명 배정할 수 있다."""

    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, verbose_name="학기")
    code = models.CharField("과목 코드", max_length=30)
    name = models.CharField("과목명", max_length=100)
    studio = models.ForeignKey(Studio, on_delete=models.PROTECT, verbose_name="지정 스튜디오")
    professors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="CourseProfessor",
        related_name="courses",
        verbose_name="담당 교수",
        blank=True,
    )
    designer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="designed_courses",
        limit_choices_to={"role": "DESIGNER"},
        verbose_name="담당 교수설계자",
    )
    is_active = models.BooleanField("사용 중", default=True)

    class Meta:
        verbose_name = "과목"
        verbose_name_plural = "과목"
        ordering = ["semester", "name"]
        constraints = [
            models.UniqueConstraint(fields=["semester", "code"], name="uniq_course_per_semester"),
        ]

    def __str__(self):
        return f"[{self.semester}] {self.name}"


class CourseProfessor(models.Model):
    """과목과 담당 교수 연결 (한 과목에 여러 교수, 한 교수가 여러 과목 가능)."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, verbose_name="과목")
    professor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "PROFESSOR"},
        verbose_name="교수",
    )

    class Meta:
        verbose_name = "과목 담당 교수"
        verbose_name_plural = "과목 담당 교수"
        constraints = [
            models.UniqueConstraint(fields=["course", "professor"], name="uniq_course_professor"),
        ]

    def __str__(self):
        return f"{self.course.name} - {self.professor.name}"

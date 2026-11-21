from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # manage.py createsuperuser 로 만든 계정은 슈퍼관리자 역할을 가진다.
        extra_fields.setdefault("role", User.Role.SUPER)
        extra_fields.setdefault("must_change_password", False)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """모든 계정(슈퍼관리자, 스튜디오 담당자, 교수).

    로그인 ID는 username 필드를 쓰며 학교 이메일을 넣는다.
    비밀번호는 Django가 암호화(PBKDF2)해서 저장한다.
    """

    class Role(models.TextChoices):
        SUPER = "SUPER", "슈퍼관리자"
        STAFF = "STAFF", "스튜디오 담당자"
        PROFESSOR = "PROFESSOR", "교수"

    name = models.CharField("이름", max_length=50)
    phone = models.CharField("연락처", max_length=30, blank=True)
    role = models.CharField("역할", max_length=10, choices=Role.choices, default=Role.PROFESSOR)
    must_change_password = models.BooleanField("비밀번호 변경 필요", default=True)

    REQUIRED_FIELDS = ["email", "name"]

    objects = UserManager()

    class Meta:
        verbose_name = "사용자"
        verbose_name_plural = "사용자"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        # 슈퍼관리자는 Django 관리자 화면 권한도 함께 가진다.
        if self.role == self.Role.SUPER:
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)

    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER

    @property
    def is_studio_staff(self):
        return self.role == self.Role.STAFF

    @property
    def is_professor(self):
        return self.role == self.Role.PROFESSOR

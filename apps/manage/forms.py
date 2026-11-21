from django import forms
from django.core.validators import validate_email

from apps.accounts.models import User
from apps.studios.models import Course, Semester

INPUT = {"class": "form-control"}
SELECT = {"class": "form-select"}


class CourseForm(forms.ModelForm):
    professors = forms.ModelMultipleChoiceField(
        User.objects.none(), required=False, label="담당 교수",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 10}),
        help_text="Ctrl(맥은 ⌘)을 누른 채 클릭하면 여러 명을 고를 수 있습니다.",
    )

    class Meta:
        model = Course
        fields = ["semester", "code", "name", "studio", "professors", "is_active"]
        widgets = {
            "semester": forms.Select(attrs=SELECT),
            "code": forms.TextInput(attrs=INPUT),
            "name": forms.TextInput(attrs=INPUT),
            "studio": forms.Select(attrs=SELECT),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, studios, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["studio"].queryset = studios
        self.fields["professors"].queryset = User.objects.filter(role=User.Role.PROFESSOR, is_active=True)
        if self.instance.pk:
            self.initial["professors"] = list(self.instance.professors.values_list("pk", flat=True))

    def clean(self):
        data = super().clean()
        sem, code = data.get("semester"), data.get("code")
        if sem and code and Course.objects.filter(semester=sem, code=code).exclude(pk=self.instance.pk).exists():
            self.add_error("code", "이 학기에 같은 과목 코드가 이미 있습니다.")
        return data

    def _get_validation_exclusions(self):
        # 과목 코드 중복은 clean()에서 한국어로 안내하므로 모델 제약 검사에서는 뺀다.
        return super()._get_validation_exclusions() | {"semester", "code"}

    def save(self, commit=True):
        course = super().save(commit=False)
        course.save()
        course.professors.set(self.cleaned_data["professors"])
        return course


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "name", "phone", "role", "is_active"]
        labels = {"username": "아이디 (학교 이메일)", "is_active": "사용 중"}
        widgets = {
            "username": forms.EmailInput(attrs=INPUT),
            "name": forms.TextInput(attrs=INPUT),
            "phone": forms.TextInput(attrs=INPUT),
            "role": forms.Select(attrs=SELECT),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = ""
        if not actor.is_super_admin:
            # 담당자는 교수 계정만 만들고 고칠 수 있다.
            del self.fields["role"]
        if self.instance.pk and self.instance.pk == actor.pk:
            # 자기 자신을 비활성화하거나 역할을 바꾸지 못하게
            self.fields.pop("is_active", None)
            self.fields.pop("role", None)

    def clean_username(self):
        value = self.cleaned_data["username"].strip().lower()
        validate_email(value)
        if User.objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("이미 등록된 아이디입니다.")
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = user.username
        if commit:
            user.save()
        return user


class ImportForm(forms.Form):
    file = forms.FileField(label="CSV 파일", widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".csv"}))
    semester = forms.ModelChoiceField(
        Semester.objects.all(), label="과목 코드 기준 학기", required=False,
        empty_label="(과목 배정 안 함)", widget=forms.Select(attrs=SELECT),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = Semester.objects.filter(is_current=True).first() or Semester.objects.first()
        if current:
            self.fields["semester"].initial = current.pk

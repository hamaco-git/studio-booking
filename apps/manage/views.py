"""담당자·슈퍼관리자 관리 화면: 학기, 과목·교수 배정, 계정, CSV 일괄 등록, 작업 이력."""

import csv

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Value
from django.db.models.functions import Replace
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.phone import digits as phone_digits
from apps.booking import audit
from apps.booking.models import AuditLog
from apps.booking.permissions import editable_studios, staff_required
from apps.studios.models import Course, Semester

from . import services
from .forms import CourseForm, CourseImportForm, ImportForm, UserForm

# ── 학기 ──────────────────────────────────────────────────


class SemesterForm(forms.ModelForm):
    class Meta:
        model = Semester
        fields = ["name", "start_date", "end_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "예: 2027-1"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
        }

    make_current = forms.BooleanField(label="현재 학기로 지정", required=False,
                                      widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            raise forms.ValidationError("종료일은 시작일보다 늦어야 합니다.")
        return data


@staff_required
def semesters(request):
    form = SemesterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if form.cleaned_data["make_current"]:
                Semester.objects.update(is_current=False)
            s = form.save(commit=False)
            s.is_current = form.cleaned_data["make_current"]
            s.save()
        audit.log(request.user, AuditLog.Action.CREATE, s, after=audit.snapshot(s))
        messages.success(request, f"학기 {s.name}을(를) 등록했습니다.")
        return redirect("manage:semesters")
    rows = Semester.objects.annotate(n=Count("course"))
    return render(request, "manage/semesters.html", {"form": form, "rows": rows})


@staff_required
@require_POST
def semester_current(request, pk):
    s = get_object_or_404(Semester, pk=pk)
    with transaction.atomic():
        Semester.objects.update(is_current=False)
        Semester.objects.filter(pk=pk).update(is_current=True)
    messages.success(request, f"{s.name}을(를) 현재 학기로 정했습니다.")
    return redirect("manage:semesters")


# ── 과목·교수 배정 ─────────────────────────────────────────


def _default_semester(request):
    sid = request.GET.get("semester")
    if sid and sid.isdigit():
        return Semester.objects.filter(pk=sid).first()
    return Semester.objects.filter(is_current=True).first() or Semester.objects.first()


@staff_required
def courses(request):
    semester = _default_semester(request)
    qs = Course.objects.filter(semester=semester).select_related("studio", "designer").prefetch_related("professors")
    sid = request.GET.get("studio")
    if sid and sid.isdigit():
        qs = qs.filter(studio_id=sid)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(professors__name__icontains=q)
                       | Q(designer__name__icontains=q)).distinct()
    editable_ids = set(editable_studios(request.user).values_list("pk", flat=True))
    from apps.studios.models import Studio

    return render(request, "manage/courses.html", {
        "semester": semester, "semesters": Semester.objects.all(), "studios": Studio.objects.filter(is_active=True),
        "rows": [(c, c.studio_id in editable_ids) for c in qs.order_by("studio__code", "name")],
        "sid": sid or "", "q": q,
    })


@staff_required
def course_edit(request, pk=None):
    studios = editable_studios(request.user)
    course = get_object_or_404(Course, pk=pk) if pk else None
    if course and not studios.filter(pk=course.studio_id).exists():
        raise PermissionDenied
    before = audit.snapshot(course) if course else None
    if before is not None:
        before["professors"] = list(course.professors.values_list("name", flat=True))
    initial = {}
    if not course:
        sem = _default_semester(request)
        initial = {"semester": sem.pk if sem else None, "is_active": True}
    form = CourseForm(request.POST or None, instance=course, studios=studios, initial=initial)
    if request.method == "POST" and form.is_valid():
        c = form.save()
        after = audit.snapshot(c)
        after["professors"] = list(c.professors.values_list("name", flat=True))
        audit.log(request.user, AuditLog.Action.UPDATE if course else AuditLog.Action.CREATE, c,
                  before=before, after=after)
        messages.success(request, f"과목 '{c.name}'을(를) 저장했습니다.")
        return redirect(f"{reverse('manage:courses')}?semester={c.semester_id}")
    return render(request, "manage/course_edit.html", {"form": form, "course": course})


# ── 계정 ──────────────────────────────────────────────────


def _manageable_users(actor):
    qs = User.objects.all()
    if not actor.is_super_admin:
        qs = qs.filter(role=User.Role.PROFESSOR)
    return qs


@staff_required
def users(request):
    qs = _manageable_users(request.user).prefetch_related("courses")
    role = request.GET.get("role", "")
    if role in User.Role.values:
        qs = qs.filter(role=role)
    if request.GET.get("inactive") != "1":
        qs = qs.filter(is_active=True)
    if request.GET.get("nophone") == "1":
        qs = qs.filter(phone="")
    q = (request.GET.get("q") or "").strip()
    if q:
        cond = Q(name__icontains=q) | Q(username__icontains=q)
        d = phone_digits(q)
        if len(d) >= 4:
            # 휴대폰 번호는 하이픈 유무와 관계없이 찾는다 (예: 12345678 → 010-1234-5678)
            qs = qs.annotate(phone_d=Replace("phone", Value("-"), Value("")))
            cond |= Q(phone_d__contains=d)
        qs = qs.filter(cond)
    page = Paginator(qs.order_by("role", "name"), 50).get_page(request.GET.get("page"))
    return render(request, "manage/users.html", {
        "page": page, "role": role, "q": q, "inactive": request.GET.get("inactive", ""),
        "nophone": request.GET.get("nophone", ""),
        "roles": User.Role.choices if request.user.is_super_admin else [],
    })


@staff_required
def user_edit(request, pk=None):
    target = get_object_or_404(_manageable_users(request.user), pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=target, actor=request.user)
    if request.method == "POST" and form.is_valid():
        if target:
            before = {k: form.initial.get(k) for k in ("username", "name", "phone", "role", "is_active")}
            u = form.save()
            services.log_update(request.user, u, before)
            messages.success(request, f"{u.name} 계정을 저장했습니다.")
        else:
            u = form.save(commit=False)
            if not request.user.is_super_admin:
                u.role = User.Role.PROFESSOR
            pw = services.create_user(request.user, u)
            messages.success(request, f"{u.name} 계정을 만들었습니다. 아이디 {u.username} / 임시 비밀번호 {pw} "
                                      "(이 화면을 벗어나면 다시 볼 수 없습니다. 첫 로그인 때 비밀번호를 바꾸게 됩니다.)")
        return redirect("manage:user_edit", pk=u.pk)
    return render(request, "manage/user_edit.html", {"form": form, "target": target})


@staff_required
@require_POST
def user_reset_password(request, pk):
    target = get_object_or_404(_manageable_users(request.user), pk=pk)
    pw = services.reset_password(request.user, target)
    messages.success(request, f"{target.name}의 비밀번호를 초기화했습니다. 임시 비밀번호: {pw} "
                              "(첫 로그인 때 새 비밀번호로 바꾸게 됩니다.)")
    return redirect("manage:user_edit", pk=pk)


# ── CSV 일괄 등록 ──────────────────────────────────────────


@staff_required
def users_import(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    results = None
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        if f.size > 1024 * 1024:
            form.add_error("file", "1MB 이하 파일만 올릴 수 있습니다.")
        else:
            try:
                text = services.decode_csv(f.read())
            except ValidationError as e:
                form.add_error("file", e.messages[0])
            else:
                results = services.import_professors(request.user, text, form.cleaned_data["semester"])
                request.session["import_result"] = results
                created = sum(r["status"] == "생성" for r in results)
                errors = sum(r["status"] == "오류" for r in results)
                messages.success(request, f"처리 완료: 새 계정 {created}개, 오류 {errors}건.")
    return render(request, "manage/users_import.html", {"form": form, "results": results,
                                                         "headers": services.CSV_HEADERS})


def _csv_response(name, rows):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    resp.write("﻿")  # 엑셀에서 한글이 깨지지 않도록 BOM
    w = csv.writer(resp)
    for r in rows:
        w.writerow(r)
    return resp


@staff_required
def users_import_template(request):
    return _csv_response("professors_template.csv", [
        services.CSV_HEADERS,
        ["hong", "홍길동", "010-0000-0000", "C101;C102"],
    ])


@staff_required
def users_import_result(request):
    results = request.session.pop("import_result", None)
    if not results:
        messages.info(request, "내려받을 결과가 없습니다. (결과는 한 번만 내려받을 수 있습니다)")
        return redirect("manage:users_import")
    return _csv_response("import_result.csv", [["행", "아이디", "이름", "결과", "임시 비밀번호", "비고"]] + [
        [r["row"], r["username"], r["name"], r["status"], r["password"], r["message"]] for r in results
    ])


@staff_required
def courses_import(request):
    """과목 CSV 일괄 등록: 올리면 먼저 미리보기, '등록하기'를 눌러야 저장한다."""
    form = CourseImportForm(request.POST or None, request.FILES or None)
    results, applied = None, False
    if request.method == "POST" and request.POST.get("step") == "apply":
        saved = request.session.pop("course_import", None)
        if not saved:
            messages.info(request, "미리보기가 만료되었습니다. 파일을 다시 올려 주세요.")
            return redirect("manage:courses_import")
        semester = Semester.objects.filter(pk=saved["semester"]).first() if saved["semester"] else None
        results = services.parse_courses(request.user, saved["text"], semester)
        n = services.apply_courses(request.user, results)
        errors = sum(r["status"] == "오류" for r in results)
        messages.success(request, f"과목 {n}개를 저장했습니다." + (f" 오류 {errors}건은 건너뛰었습니다." if errors else ""))
        applied = True
        form = CourseImportForm()
    elif request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        if f.size > 1024 * 1024:
            form.add_error("file", "1MB 이하 파일만 올릴 수 있습니다.")
        else:
            try:
                text = services.decode_csv(f.read())
            except ValidationError as e:
                form.add_error("file", e.messages[0])
            else:
                semester = form.cleaned_data["semester"]
                results = services.parse_courses(request.user, text, semester)
                request.session["course_import"] = {"text": text, "semester": semester.pk if semester else None}
    counts = {}
    for r in results or []:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return render(request, "manage/courses_import.html", {
        "form": form, "results": results, "applied": applied, "counts": counts,
        "can_apply": bool(counts.get("신규") or counts.get("갱신")),
        "headers": services.COURSE_CSV_HEADERS,
    })


@staff_required
def courses_import_template(request):
    from apps.studios.models import Studio

    sem = Semester.objects.filter(is_current=True).first() or Semester.objects.first()
    sem_name = sem.name if sem else "2027-1"
    studio = editable_studios(request.user).first() or Studio.objects.first()
    code = studio.code if studio else "studio1"
    return _csv_response("courses_template.csv", [
        services.COURSE_CSV_HEADERS,
        [sem_name, "C101", "영상제작론", code, "prof01;prof02", "designer01", "사용"],
        [sem_name, "C102", "디지털미디어", code, "prof03", "", ""],
    ])


@staff_required
def courses_export(request):
    """선택한 학기의 과목을 일괄 등록 양식 그대로 내려받는다 (수정 후 다시 올리기용)."""
    semester = _default_semester(request)
    qs = Course.objects.filter(semester=semester).select_related("studio", "designer") \
        .prefetch_related("professors").order_by("studio__code", "code")
    return _csv_response(f"courses_{semester.name if semester else ''}.csv", [services.COURSE_CSV_HEADERS] + [
        [c.semester.name, c.code, c.name, c.studio.code, ";".join(p.username for p in c.professors.all()),
         c.designer.username if c.designer else "", "사용" if c.is_active else "중지"] for c in qs
    ])


# ── 작업 이력 ─────────────────────────────────────────────

TABLE_LABELS = {
    "booking_reservation": "예약",
    "booking_openslot": "예약 가능 슬롯",
    "booking_blackout": "촬영 불가일",
    "studios_course": "과목",
    "studios_semester": "학기",
    "accounts_user": "계정",
}


@staff_required
def logs(request):
    """누가 언제 무엇을 생성·수정·취소·상태 변경했는지 조회 (슈퍼관리자·담당자)."""
    qs = AuditLog.objects.select_related("user")
    table = request.GET.get("table", "")
    if table in TABLE_LABELS:
        qs = qs.filter(target_table=table)
    action = request.GET.get("action", "")
    if action in AuditLog.Action.values:
        qs = qs.filter(action=action)
    start, end = parse_date(request.GET.get("start") or ""), parse_date(request.GET.get("end") or "")
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(user__name__icontains=q)
    target = (request.GET.get("target") or "").strip()
    if target:
        qs = qs.filter(summary__icontains=target)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    display = audit._Display()
    rows = [
        (log, TABLE_LABELS.get(log.target_table, log.target_table), audit.changes_text(log, display))
        for log in page
    ]
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "manage/logs.html", {
        "page": page, "rows": rows, "tables": TABLE_LABELS.items(), "table": table,
        "actions": AuditLog.Action.choices, "action": action, "target": target,
        "start": start, "end": end, "q": q, "query": params.urlencode(),
    })

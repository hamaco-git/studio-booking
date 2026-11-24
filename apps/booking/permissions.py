"""역할별 권한 규칙.

- 슈퍼관리자: 모든 스튜디오 수정 가능
- 담당자: 담당 스튜디오만 수정, 다른 스튜디오는 조회만
- 교수설계자: 담당 과목의 촬영 일정만 조회 (수정 불가)
- 교수: 담당 과목의 지정 스튜디오만 조회·예약
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from apps.studios.models import Studio


def staff_required(view):
    """담당자 또는 슈퍼관리자만 접근."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_studio_staff or request.user.is_super_admin):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def schedule_viewer_required(view):
    """담당자·슈퍼관리자·교수설계자 접근 (현황 달력, 예약 목록 조회)."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        u = request.user
        if not (u.is_studio_staff or u.is_super_admin or u.is_designer):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def editable_studios(user):
    """이 사용자가 슬롯·불가일·예약을 수정할 수 있는 스튜디오."""
    qs = Studio.objects.filter(is_active=True)
    if user.is_super_admin:
        return qs
    if user.is_studio_staff:
        return qs.filter(studiostaff__staff=user)
    return qs.none()


def viewable_studios(user):
    """이 사용자가 달력을 볼 수 있는 스튜디오."""
    qs = Studio.objects.filter(is_active=True)
    if user.is_super_admin or user.is_studio_staff:
        return qs
    if user.is_designer:
        return qs.filter(course__designer=user).distinct()
    return qs.filter(course__professors=user, course__is_active=True).distinct()


def can_edit_studio(user, studio):
    return editable_studios(user).filter(pk=studio.pk).exists()


def require_edit(user, studio):
    if studio is None:
        # 전체 스튜디오 대상(불가일)은 슈퍼관리자만
        if not user.is_super_admin:
            raise PermissionDenied
        return
    if not can_edit_studio(user, studio):
        raise PermissionDenied


def professor_required(view):
    """교수만 접근."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_professor:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper

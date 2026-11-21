from datetime import date, datetime, time

from django.forms.models import model_to_dict

from .models import AuditLog


def snapshot(obj):
    """모델 객체를 JSON으로 저장할 수 있는 dict로 변환."""
    if obj is None:
        return None
    data = model_to_dict(obj)
    data["id"] = obj.pk
    for k, v in data.items():
        if isinstance(v, (date, datetime, time)):
            data[k] = v.isoformat()
    return data


def log(user, action, obj, before=None, after=None):
    AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        target_table=obj._meta.db_table,
        target_id=obj.pk,
        before=before,
        after=after,
    )

"""작업 이력(AuditLog) 기록과 화면 표시용 도우미."""

from datetime import date, datetime, time

from django.apps import apps as django_apps

from .models import AuditLog

SKIP_FIELDS = {"password", "created_at", "updated_at"}
HIDDEN_IN_CHANGES = {"id", "created_by", "updated_by", "slot", "cancelled_at", "cancelled_by"}


def snapshot(obj):
    """모델 객체를 JSON으로 저장할 수 있는 dict로 변환 (외래키는 ID)."""
    if obj is None:
        return None
    data = {}
    for f in obj._meta.concrete_fields:
        if f.name in SKIP_FIELDS:
            continue
        v = f.value_from_object(obj)
        if isinstance(v, (date, datetime, time)):
            v = v.isoformat()
        data[f.name] = v
    data["id"] = obj.pk
    return data


def describe(obj):
    try:
        text = obj.describe() if hasattr(obj, "describe") else str(obj)
    except Exception:  # 설명을 만들다 실패해도 이력 기록은 계속
        text = ""
    return text[:200]


def log(user, action, obj, before=None, after=None):
    AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        target_table=obj._meta.db_table,
        target_id=obj.pk,
        summary=describe(obj),
        before=before,
        after=after,
    )


# ── 화면 표시 ─────────────────────────────────────────────

_MODELS = None


def _model_for(table):
    global _MODELS
    if _MODELS is None:
        _MODELS = {m._meta.db_table: m for m in django_apps.get_models()}
    return _MODELS.get(table)


class _Display:
    """이력의 필드 이름·값을 한국어로 바꿔 준다. 외래키 이름 조회는 한 화면 안에서 캐시한다."""

    def __init__(self):
        self.cache = {}

    def field(self, model, key):
        try:
            return model._meta.get_field(key) if model else None
        except Exception:
            return None

    def label(self, model, key):
        f = self.field(model, key)
        return str(f.verbose_name) if f is not None and hasattr(f, "verbose_name") else key

    def value(self, model, key, v):
        if v in (None, ""):
            return "-"
        f = self.field(model, key)
        if f is None:
            return v
        if getattr(f, "choices", None):
            return dict(f.choices).get(v, v)
        if f.is_relation and f.related_model and isinstance(v, int):
            k = (f.related_model, v)
            if k not in self.cache:
                obj = f.related_model._default_manager.filter(pk=v).first()
                self.cache[k] = getattr(obj, "code", None) or getattr(obj, "name", None) or str(obj) if obj else f"#{v}"
            return self.cache[k]
        if v is True:
            return "예"
        if v is False:
            return "아니오"
        return v


def changes_text(log_entry, display=None):
    """'상태: 확정 → 불참(노쇼), 메모: - → 늦게 연락' 같은 변경 내용 한 줄."""
    d = display or _Display()
    model = _model_for(log_entry.target_table)
    before, after = log_entry.before or {}, log_entry.after or {}
    if before and after:
        keys = [k for k in after if k in before and before.get(k) != after.get(k) and k not in HIDDEN_IN_CHANGES]
        return ", ".join(
            f"{d.label(model, k)}: {d.value(model, k, before.get(k))} → {d.value(model, k, after.get(k))}" for k in keys
        )
    data = after or before
    return ", ".join(
        f"{d.label(model, k)}: {d.value(model, k, v)}" for k, v in data.items() if k not in HIDDEN_IN_CHANGES
    )[:300]

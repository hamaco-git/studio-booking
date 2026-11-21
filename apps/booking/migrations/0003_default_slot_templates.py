from datetime import time

from django.db import migrations

DEFAULTS = [("오전", time(9), time(12), 1), ("오후", time(13), time(18), 2)]


def add_defaults(apps, schema_editor):
    SlotTemplate = apps.get_model("booking", "SlotTemplate")
    if not SlotTemplate.objects.exists():
        for label, start, end, order in DEFAULTS:
            SlotTemplate.objects.create(label=label, start_time=start, end_time=end, order=order)


class Migration(migrations.Migration):
    dependencies = [("booking", "0002_slot_template")]
    operations = [migrations.RunPython(add_defaults, migrations.RunPython.noop)]

from django.core.management.base import BaseCommand

from apps.studios.models import Studio

STUDIOS = [
    ("studio1", "Studio 1", "#4f7cff"),
    ("studio2", "Studio 2", "#2fb380"),
    ("studio3", "Studio 3", "#f0a020"),
    ("studio4", "Studio 4", "#d9534f"),
]


class Command(BaseCommand):
    help = "스튜디오 4개(studio1~studio4)를 등록한다. 이미 있으면 건너뛴다."

    def handle(self, *args, **options):
        for code, name, color in STUDIOS:
            _, created = Studio.objects.get_or_create(code=code, defaults={"name": name, "color": color})
            self.stdout.write(f"{code}: {'등록' if created else '이미 있음'}")

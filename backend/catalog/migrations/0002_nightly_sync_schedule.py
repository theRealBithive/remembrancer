"""Register the nightly ABS mirror with django-q2.

A data migration rather than an admin click so a fresh deployment is scheduled the
moment it migrates -- nobody has to remember to set it up.
"""

from django.db import migrations
from django.utils import timezone

TASK = "catalog.tasks.nightly_sync"


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(func=TASK).exists():
        return
    # 03:20 local, tomorrow: off the hour so it doesn't collide with every other
    # cron on the box, and after any overnight ABS scan has settled.
    next_run = (timezone.localtime() + timezone.timedelta(days=1)).replace(
        hour=3, minute=20, second=0, microsecond=0
    )
    Schedule.objects.create(
        name="Nightly Audiobookshelf sync",
        func=TASK,
        schedule_type="D",  # daily
        repeats=-1,
        next_run=next_run,
    )


def drop_schedule(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(func=TASK).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
        # __latest__: Schedule.name only exists after django_q's later migrations, and
        # the historical model at 0001_initial has no such field.
        ("django_q", "__latest__"),
    ]

    operations = [migrations.RunPython(create_schedule, drop_schedule)]

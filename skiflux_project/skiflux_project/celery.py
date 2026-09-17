import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skiflux_project.settings")


app = Celery("skiflux_project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "cleanup-expired-blacklisted-tokens": {
        "task": "skiflux.tasks.auth.cleanup_expired_blacklisted_tokens",
        "schedule": crontab(hour=0, minute=0),
    },
    "aggregate-behaviour-logs": {
        "task": "skiflux.tasks.content.aggregate_behaviour_logs",
        "schedule": crontab(minute=0),
    },
    "send-daily-reminders": {
        "task": "skiflux.tasks.content.send_daily_reminders",
        "schedule": crontab(minute="*/15"),
    },
    "expire-suspensions": {
        "task": "skiflux.tasks.moderation.expire_due_suspensions",
        "schedule": crontab(minute="*/30"),  # every 30 mins
    },
    "poll-support-inbox": {
        "task": "skiflux.tasks.support.poll_support_inbox",
        "schedule": timedelta(seconds=60),
    },
}


@task_postrun.connect
def close_db_connections(**kwargs):
    from django.db import connections

    for conn in connections.all():
        conn.close()

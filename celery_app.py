# celery_app.py

import os
from celery import Celery

def make_celery():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # ✅ fallback for local dev

    celery = Celery(
        "jyotishasha",
        broker=redis_url,
        backend=redis_url,
        include=["tasks"]
    )
    celery.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json']
    )
    return celery

celery = make_celery()

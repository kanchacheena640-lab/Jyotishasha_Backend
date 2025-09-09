# celery_app.py

import os
from celery import Celery

def make_celery():
    redis_url = os.getenv("REDIS_URL")
    if redis_url.startswith("rediss://"):
        # For Upstash SSL connection
        broker_use_ssl = {"ssl_cert_reqs": "CERT_NONE"}
    else:
        broker_use_ssl = None

    celery = Celery(
        "jyotishasha",
        broker=redis_url,
        backend=redis_url,
        include=["tasks"]
    )

    celery.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        broker_use_ssl=broker_use_ssl  # ⬅️ Important for rediss://
    )

    return celery

celery = make_celery()

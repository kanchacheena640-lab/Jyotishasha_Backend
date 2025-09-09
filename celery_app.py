# celery_app.py

import os
from celery import Celery

def make_celery():
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("[ERROR] REDIS_URL is missing!")
    else:
        print("[INFO] Redis URL loaded:", redis_url)

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

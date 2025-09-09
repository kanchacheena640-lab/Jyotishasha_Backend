# celery_app.py

import os
from celery import Celery

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise ValueError("[ERROR] REDIS_URL is missing or not set in Render environment variables.")
else:
    print("[INFO] Redis URL loaded successfully.")

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

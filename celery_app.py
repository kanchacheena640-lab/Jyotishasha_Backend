# celery_app.py

import os
from celery import Celery

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise ValueError("[ERROR] REDIS_URL is missing or not set in Render environment variables.")
else:
    print("[INFO] Redis URL loaded successfully:", redis_url)

celery = Celery(
    "jyotishasha",
    broker=redis_url,
    backend=redis_url,
    include=["tasks"]
)

# SSL config for rediss:// (secure Redis)
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    broker_use_ssl={"ssl_cert_reqs": "CERT_NONE"},
    redis_backend_use_ssl={"ssl_cert_reqs": "CERT_NONE"},
)

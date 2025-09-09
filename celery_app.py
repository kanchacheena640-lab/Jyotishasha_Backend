# celery_app.py

import os
from celery import Celery
import ssl

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise ValueError("[ERROR] REDIS_URL is missing or not set.")
else:
    print("[INFO] Redis URL loaded successfully:", redis_url)

celery = Celery(
    "jyotishasha",
    broker=redis_url,
    backend=redis_url,
    include=["tasks"]
)

# Use Python None (not string) for SSL setting
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE}
)

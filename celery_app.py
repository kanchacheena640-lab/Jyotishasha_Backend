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
    include=["tasks"]
)

celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    result_backend=None,  # ✅ make sure result backend is off
    worker_prefetch_multiplier=1,  # ✅ har worker ek time me ek hi task lega
    broker_transport_options={
        "visibility_timeout": 3600,  # ✅ task 1 hr tak queue me rahega agar fail ho
        "polling_interval": 10.0      # ✅ default 0.2s → ab har 1 sec me poll karega
    }
)

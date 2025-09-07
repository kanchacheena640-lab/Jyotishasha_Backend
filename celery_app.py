# celery_app.py

from celery import Celery

def make_celery():
    celery = Celery(
        "jyotishasha",
        broker="redis://localhost:6379/0",
        backend="redis://localhost:6379/0",
        include=["tasks"]  # ✅ Add this line
    )
    celery.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json']
    )
    return celery

celery = make_celery()

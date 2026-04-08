import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_EAGER = os.getenv("CELERY_EAGER", "").lower() in {"1", "true", "yes", "on"}

celery_app = Celery(
    "vectomap",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

if CELERY_EAGER:
    celery_app.conf.update(
        task_always_eager=True,
        task_store_eager_result=True,
        result_backend="cache+memory://",
        broker_url="memory://",
    )

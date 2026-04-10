"""Celery 앱 정의 — worker + beat 공용.
브로커/백엔드 URL은 환경변수에서 읽는다.
"""

import os

from celery import Celery

broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "backend_fastapi",
    broker=broker_url,
    backend=result_backend,
    include=[],
)

# 주기 태스크는 아직 정의 안 함 — beat 기동만 확인
celery_app.conf.beat_schedule = {}
celery_app.conf.timezone = "Asia/Seoul"

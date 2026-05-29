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
    include=[
        "app.modules.Agent_orchestrator.tasks",
        "app.modules.Agent_orchestrator.maintenance",
    ],
)

# 주기 태스크 스케줄 — beat worker가 자동으로 실행한다
celery_app.conf.beat_schedule = {
    # 30분 이상 running 상태로 멈춘 job을 error로 전환 (10분마다)
    "cleanup-stale-jobs": {
        "task": "agent_orchestrator.cleanup_stale_jobs",
        "schedule": 600,
    },
    # 24시간 이상 경과한 done/error job을 메모리에서 삭제 (1시간마다)
    "purge-old-jobs": {
        "task": "agent_orchestrator.purge_old_completed_jobs",
        "schedule": 3600,
    },
    # callback 전송 실패 job을 재시도 (5분마다)
    "retry-failed-callbacks": {
        "task": "agent_orchestrator.retry_failed_callbacks",
        "schedule": 300,
    },
}
celery_app.conf.timezone = "Asia/Seoul"

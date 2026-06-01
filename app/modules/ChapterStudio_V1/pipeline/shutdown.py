"""강의 배치 완료 후 커넥터 shutdown 훅 호출 유틸.

[비용 통제 설계]
Modal은 running 컨테이너 시간만 과금한다. 앱이 배포(deployed) 상태여도 요청이 없으면
scaledown_window(30초) 후 자동 scale-to-zero → 컨테이너 비용 0. 따라서 배포 자체를
내릴(un-deploy) 필요가 없다. 비용 통제는 deploy/modal_app.py의 scaledown_window=30s가
담당하며, 이 유틸은 그 흐름에서 후처리 훅을 호출하는 진입점 역할만 한다.

[connector.shutdown() 계약]
- 기본(CHAPTERSTUDIO_MODAL_TEARDOWN=false): no-op + info 로그 → False 반환.
- teardown 스위치 ON: `modal app stop`(un-deploy) 실행 → True/False 반환.
  라이브 서비스에서 teardown=true는 다음 요청을 깨뜨리므로 절대 금지.

[codex/claude]
supports("shutdown")=False → _can_shutdown()이 False → 이 유틸 자체가 no-op(False 반환).

공개 API:
    - shutdown_text_connector() : 활성 텍스트 커넥터의 shutdown 훅을 호출한다(대부분 no-op).
"""
from __future__ import annotations

import asyncio

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector
from app.modules.ChapterStudio_V1.common.logging import logger


async def shutdown_text_connector() -> bool:
    """활성 텍스트 커넥터의 shutdown 훅을 호출한다(기본 no-op, teardown 스위치 ON 시만 un-deploy).

    scaledown_window가 이미 idle 컨테이너 비용을 0으로 만드므로, 이 함수는 실제 서비스
    흐름에서 대부분 False(no-op)를 반환한다. teardown 경로는 decommission 전용이다.
    반환값: 실제 teardown을 수행해 성공했으면 True, no-op이거나 실패면 False.
    """
    try:
        connector = get_text_connector()
    except ConnectorError as exc:
        logger.warning("shutdown: 텍스트 커넥터 조회 실패(graceful): {}", exc)
        return False
    if not _can_shutdown(connector):
        return False
    try:
        return bool(await connector.shutdown())
    except (ConnectorError, OSError, asyncio.TimeoutError, RuntimeError) as exc:
        logger.warning("shutdown: 커넥터 shutdown 훅 실패(graceful): {}", exc)
        return False


def _can_shutdown(connector: object) -> bool:
    """커넥터가 shutdown 기능을 명시 지원하고 실제 메서드를 가졌는지 확인한다."""
    supports = getattr(connector, "supports", None)
    shutdown = getattr(connector, "shutdown", None)
    if not callable(supports) or not callable(shutdown):
        return False
    return bool(supports("shutdown"))


__all__ = ["shutdown_text_connector"]

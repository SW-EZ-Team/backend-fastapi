"""LangGraph ASR 폴백 상태 타입 정의.

ASRState 는 그래프가 tier 사이를 이동하며 누적하는 불변 스냅샷이다.
AttemptRecord 는 각 tier 시도 결과를 기록하는 단위 구조다.
이 파일은 schemas 이외의 어떤 커넥터 모듈도 import 하지 않는다 (SRP).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypedDict

from ai_connectors.schemas import ASRRequest, ASRResponse

if TYPE_CHECKING:
    # 순환 import 방지 — 타입 힌트 전용으로만 참조한다
    pass


class AttemptRecord(TypedDict):
    """단일 tier 시도 결과 기록."""

    tier: int                    # 0, 1, 2 — tier 순서 인덱스
    model_name: str              # 예: "mlx-whisper-turbo"
    text: str                    # 전사 결과 (실패 시 빈 문자열)
    latency_ms: float            # 추론 소요 시간 (ms)
    quality_score: float         # 0.0 ~ 1.0 (높을수록 좋음)
    quality_reason: str          # "ok" / "empty" / "hallucination_loop" / "low_char_rate" / "error:{msg}"
    response: ASRResponse | None  # 원본 응답 (성공 시 채워짐, 실패 시 None)


class ASRState(TypedDict):
    """LangGraph StateGraph 의 전이 상태.

    tier_factories 와 tier_model_names 는 호출 시점에 주입되어
    그래프 실행 동안 불변으로 유지된다.
    """

    request: ASRRequest
    tier_factories: list[Callable[[], Any]]  # ASRConnector 를 반환하는 지연 로드 팩토리 목록
    tier_model_names: list[str]              # tier_factories 와 동일 인덱스의 모델 이름 (로깅용)
    current_tier: int                         # 현재 시도 중인 tier 인덱스
    attempts: list[AttemptRecord]             # 시도 기록 누적 목록
    done: bool                                # 종료 플래그 (품질 통과 or tier 소진)

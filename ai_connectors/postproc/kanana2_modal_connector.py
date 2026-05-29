"""Modal GPU 배포용 OCR 후처리 LLM 커넥터 스텁.

미래 배포 Phase 에서 Modal 에 올린 Qwen 계열/Kanana 원본 FP16 가중치로
후처리를 오프로드할 자리 표시자. 현재는 NotImplementedError 만 던져
registry 에 등록은 되면서 실제 호출 시점에 로컬 MLX 로 유도한다.
"""
from __future__ import annotations

from ..postproc_schemas import PostprocRequest, PostprocResponse


class Kanana2ModalConnector:
    """Modal GPU 에서 후처리 LLM 을 호출하는 커넥터 (미구현)."""

    name: str = "kanana2-modal"

    async def refine(self, request: PostprocRequest) -> PostprocResponse:
        """배포 Phase 에서 Modal 엔드포인트 호출 로직으로 교체될 예정."""
        raise NotImplementedError(
            "Modal 배포 커넥터는 배포 Phase 에서 구현 예정입니다. "
            "로컬 개발에서는 AI_MODEL_POSTPROC=kanana2-mlx 를 사용하세요.",
        )

    def supports(self, feature: str) -> bool:
        """미구현 상태 — 어떤 기능도 지원한다고 보고하지 않는다."""
        return False

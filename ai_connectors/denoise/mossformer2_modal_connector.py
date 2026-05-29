"""Modal GPU 배포용 MossFormer2 디노이즈 커넥터 스텁.

미래 배포 Phase에서 Modal의 B200/A100 GPU로 clearvoice를 실행할 자리 표시자.
지금은 NotImplementedError만 던진다 (registry에서 인스턴스화는 가능해야 함).
"""
from __future__ import annotations

from ..schemas import DenoiseRequest, DenoiseResponse


class MossFormer2ModalConnector:
    """Modal GPU에서 MossFormer2를 호출하는 커넥터 (미구현)."""

    # 등록 키와 동일
    name: str = "mossformer2-modal"

    async def denoise(self, request: DenoiseRequest) -> DenoiseResponse:
        """배포 Phase에서 Modal 엔드포인트 호출 로직으로 교체될 예정."""
        raise NotImplementedError(
            "Modal 배포 커넥터는 배포 Phase에서 구현 예정입니다. "
            "로컬 개발에서는 AI_MODEL_DENOISE=mossformer2-se-48k를 사용하세요.",
        )

    def supports(self, feature: str) -> bool:
        """미구현 상태 — 어떤 기능도 지원한다고 보고하지 않는다."""
        return False

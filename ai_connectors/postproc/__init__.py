"""OCR 후처리 LLM 커넥터 서브 패키지.

배포 Modal GPU 런타임 커넥터를 담는다.
등록은 상위 `ai_connectors.registry.POSTPROC_CONNECTORS` 에서 수행한다.
"""

from .kanana2_modal_connector import Kanana2ModalConnector

__all__ = ["Kanana2ModalConnector"]

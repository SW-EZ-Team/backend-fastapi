"""OCR 후처리 LLM 커넥터 서브 패키지.

각 런타임 (로컬 Mac MLX, 배포 Modal GPU 등) 별로 파일 하나.
등록은 상위 `ai_connectors.registry.POSTPROC_CONNECTORS` 에서 수행한다.
"""

from .kanana2_mlx_connector import Kanana2MlxConnector

__all__ = ["Kanana2MlxConnector"]

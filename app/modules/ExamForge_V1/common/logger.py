"""공통 로거 팩토리 모듈."""
from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """모듈명을 받아 표준 포맷의 로거를 반환한다."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)
    return logger

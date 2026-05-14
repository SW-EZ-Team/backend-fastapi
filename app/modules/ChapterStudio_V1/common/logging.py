from __future__ import annotations

import sys

from loguru import logger

from app.modules.ChapterStudio_V1.common.config import log_level

logger.remove()
logger.add(
    sys.stderr,
    level=log_level(),
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name} | {message}",
    backtrace=False,
    diagnose=False,
)

__all__ = ["logger"]

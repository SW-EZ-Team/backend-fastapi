"""로거 팩토리.

모든 모듈이 logging.getLogger() 호출 대신 여기 get_logger(name)을 쓰도록 통일.
초기화(포맷, 레벨)를 한 곳에서 관리해 로그 스타일 드리프트를 막는다.
"""
from __future__ import annotations

import logging
import os
import sys

# global 대신 딕셔너리 홀더 패턴 사용 — 루트 로거 중복 초기화 방지
_LOG_STATE: dict[str, bool] = {"initialized": False}


def _ensure_root_logger() -> None:
    """루트 로거에 stdout 핸들러를 한 번만 부착한다."""
    if _LOG_STATE["initialized"]:
        return
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    # 이미 uvicorn 등이 핸들러를 달아놓은 경우 중복 로그 방지 위해 먼저 검사
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(handler)
    _LOG_STATE["initialized"] = True


def get_logger(name: str) -> logging.Logger:
    """이름 있는 로거 반환. 루트 초기화는 자동."""
    _ensure_root_logger()
    return logging.getLogger(name)

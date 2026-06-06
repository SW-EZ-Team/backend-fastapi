"""Telegram 서비스 내부에서 공유하는 구조적 타입 프로토콜 정의."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TelegramClientLike(Protocol):
    """send_message를 가진 객체이면 어떤 구현체든 수용하는 구조적 타입.

    TelegramClient 구체 클래스와 테스트 더미 클라이언트 모두를 허용하기 위해
    Protocol을 사용한다. 호출자는 이 타입을 기준으로 의존한다.
    """

    async def send_message(self, token: str, chat_id: str, message: str) -> object:
        """메시지 전송 — 반환값은 호출자가 사용하지 않는다."""
        ...

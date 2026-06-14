"""텍스트 도메인 폴백 커넥터.

ChapterStudio_V1 의 FailoverAIConnector 패턴을 top-level ai_connectors 스키마/예외에
맞춰 옮긴 것이다. 주 커넥터가 연속 실패하면 대체 커넥터 체인으로 회로를 넘긴다.
generate / generate_batch 를 모두 지원해 Gemini 텍스트 커넥터 인터페이스와 호환된다.

폴백 체인: fallback_factories 순서대로 시도한다(예: Gemini → OpenAI → Claude).
폴백이 AuthError(키 무효)를 올리면 그 폴백은 영구 제외하고 다음 폴백으로
진행한다 — 잘못된 키 하나가 요청 전체를 실패시키는 것을 막는다.
기존 단일 fallback_factory 시그니처는 하위 호환으로 유지한다.

주 커넥터 복귀(recovery): 폴백 전환은 영구가 아니다. TEXT_FALLBACK_RECOVERY_SEC
(기본 60초, 0 이하면 비활성=기존 영구 전환 동작) 가 지나면 다음 요청에서 주
커넥터를 1회 다시 시도하고, 성공하면 회로를 닫아 주 커넥터로 복귀한다.
실패하면 다음 복귀 시도를 같은 간격만큼 뒤로 미루고 폴백 체인으로 진행한다 —
TEXT_FALLBACK_AFTER_FAILURES=1 같은 낮은 임계값에서 일시 장애 한 번이 프로세스
수명 내내 폴백에 고정되는 문제를 막는다.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator, Sequence

from .errors import AuthError, ConnectorError
from .text_schemas import ChapterAIRequest, ChapterAIResponse

_LOG = logging.getLogger(__name__)

# 주 커넥터 복귀 시도 간격 기본값(초) — 0 이하면 복귀 비활성(영구 폴백)
_DEFAULT_RECOVERY_SEC = 60.0


def _recovery_interval_sec() -> float:
    """TEXT_FALLBACK_RECOVERY_SEC 환경변수를 읽는다(호출 시마다 — 테스트 monkeypatch 가능)."""
    raw = os.getenv("TEXT_FALLBACK_RECOVERY_SEC")
    if raw is None or not raw.strip():
        return _DEFAULT_RECOVERY_SEC
    try:
        return float(raw.strip())
    except ValueError:
        return _DEFAULT_RECOVERY_SEC


class FailoverAIConnector:
    """주 커넥터가 연속 실패하면 대체 커넥터 체인으로 회로를 넘긴다."""

    def __init__(
        self,
        primary: object,
        fallback_factory: Callable[[], object] | None = None,
        *,
        fallback_factories: Sequence[Callable[[], object]] | None = None,
        name: str,
        failure_threshold: int = 3,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold는 1 이상이어야 한다.")
        # 하위 호환: 단일 fallback_factory 는 길이 1짜리 체인으로 흡수한다
        if fallback_factories is None:
            if fallback_factory is None:
                raise ValueError("fallback_factory 또는 fallback_factories 가 필요하다.")
            fallback_factories = (fallback_factory,)
        elif fallback_factory is not None:
            raise ValueError("fallback_factory 와 fallback_factories 는 동시에 줄 수 없다.")
        if not fallback_factories:
            raise ValueError("fallback_factories 는 비어 있을 수 없다.")
        self.name = name
        self._primary = primary
        self._fallback_factories: list[Callable[[], object]] = list(fallback_factories)
        self._fallbacks: list[object | None] = [None] * len(self._fallback_factories)
        # AuthError 로 영구 제외된 폴백 인덱스 — 무효 키 폴백의 실패 로그 폭주 방지
        self._skipped: set[int] = set()
        self._failure_threshold = failure_threshold
        self._failure_count = 0
        self._fallback_active = False
        self._last_failure = ""
        # 주 커넥터 복귀 시도가 허용되는 monotonic 시각 — 폴백 전환/복귀 실패 시 갱신
        self._primary_retry_at: float | None = None

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def last_failure(self) -> str:
        return self._last_failure

    @property
    def primary_name(self) -> str:
        return getattr(self._primary, "name", "primary")

    @property
    def fallback_name(self) -> str:
        for _index, connector in self._iter_fallbacks():
            return getattr(connector, "name", "fallback")
        return "fallback"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        if self._fallback_active:
            # 복귀 간격이 지났으면 주 커넥터를 1회 다시 시도한다(성공 시 회로 닫힘)
            if self._primary_probe_due():
                recovered = await self._probe_primary(
                    lambda: self._primary.generate(req)
                )
                if recovered is not None:
                    return recovered
            return await self._generate_via_fallbacks(req)

        last_error: ConnectorError | None = None
        while not self._fallback_active:
            try:
                response = await self._primary.generate(req)
                self._failure_count = 0
                self._last_failure = ""
                return response
            except ConnectorError as exc:
                last_error = exc
                self._record_failure(exc, count=1)

        if last_error is not None:
            self._last_failure = str(last_error)
        return await self._generate_via_fallbacks(req)

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        if not reqs:
            return []
        if self._fallback_active:
            # 복귀 간격이 지났으면 주 커넥터를 1회 다시 시도한다(성공 시 회로 닫힘)
            if self._primary_probe_due():
                recovered = await self._probe_primary(
                    lambda: self._primary.generate_batch(reqs)
                )
                if recovered is not None:
                    return recovered
            return await self._generate_batch_via_fallbacks(reqs)

        last_error: ConnectorError | None = None
        while not self._fallback_active:
            try:
                responses = await self._primary.generate_batch(reqs)
                self._failure_count = 0
                self._last_failure = ""
                return responses
            except ConnectorError as exc:
                last_error = exc
                self._record_failure(exc, count=len(reqs))

        if last_error is not None:
            self._last_failure = str(last_error)
        return await self._generate_batch_via_fallbacks(reqs)

    def supports(self, feature: str) -> bool:
        if feature == "fallback":
            return True
        if self._primary.supports(feature):
            return True
        return any(
            connector.supports(feature) for _index, connector in self._iter_fallbacks()
        )

    async def aclose(self) -> None:
        for connector in (self._primary, *self._fallbacks):
            close = getattr(connector, "aclose", None)
            if close is not None:
                await close()

    def _iter_fallbacks(self) -> Iterator[tuple[int, object]]:
        """제외되지 않은 폴백 커넥터를 순서대로 지연 생성하며 순회한다.

        생성 단계 AuthError(키 미설정/무효)는 해당 폴백을 영구 제외하고
        다음 폴백으로 넘어간다.
        """
        for index, factory in enumerate(self._fallback_factories):
            if index in self._skipped:
                continue
            connector = self._fallbacks[index]
            if connector is None:
                try:
                    connector = factory()
                except AuthError as exc:
                    self._skipped.add(index)
                    _LOG.warning(
                        "%s: 폴백 커넥터 생성 실패(AuthError) — 영구 제외: %s",
                        self.name,
                        exc,
                    )
                    continue
                self._fallbacks[index] = connector
            yield index, connector

    async def _generate_via_fallbacks(self, req: ChapterAIRequest) -> ChapterAIResponse:
        last_error: ConnectorError | None = None
        for index, connector in self._iter_fallbacks():
            try:
                return await connector.generate(req)
            except AuthError as exc:
                last_error = self._skip_fallback(index, connector, exc)
            except ConnectorError as exc:
                last_error = self._note_fallback_failure(connector, exc)
        raise last_error or ConnectorError(f"{self.name}: 사용 가능한 폴백 커넥터가 없다.")

    async def _generate_batch_via_fallbacks(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        last_error: ConnectorError | None = None
        for index, connector in self._iter_fallbacks():
            try:
                return await connector.generate_batch(reqs)
            except AuthError as exc:
                last_error = self._skip_fallback(index, connector, exc)
            except ConnectorError as exc:
                last_error = self._note_fallback_failure(connector, exc)
        raise last_error or ConnectorError(f"{self.name}: 사용 가능한 폴백 커넥터가 없다.")

    def _skip_fallback(
        self, index: int, connector: object, exc: AuthError
    ) -> ConnectorError:
        """AuthError 폴백을 영구 제외하고 다음 폴백 진행을 기록한다."""
        self._skipped.add(index)
        self._last_failure = str(exc)
        _LOG.warning(
            "%s: 폴백 %s AuthError — 영구 제외하고 다음 폴백으로 진행: %s",
            self.name,
            getattr(connector, "name", "fallback"),
            exc,
        )
        return exc

    def _note_fallback_failure(
        self, connector: object, exc: ConnectorError
    ) -> ConnectorError:
        """이번 요청에 한해 실패를 기록하고 다음 폴백으로 진행한다(영구 제외 아님)."""
        self._last_failure = str(exc)
        _LOG.warning(
            "%s: 폴백 %s 실패 — 다음 폴백 시도: %s",
            self.name,
            getattr(connector, "name", "fallback"),
            exc,
        )
        return exc

    def _record_failure(self, exc: ConnectorError, *, count: int) -> None:
        self._failure_count += count
        self._last_failure = str(exc)
        if self._failure_count >= self._failure_threshold:
            self._fallback_active = True
            self._schedule_primary_probe()

    # ── 주 커넥터 복귀(recovery) ──────────────────────────────────────

    def _schedule_primary_probe(self) -> None:
        """다음 주 커넥터 복귀 시도 시각을 예약한다. 간격이 0 이하면 비활성(영구 폴백)."""
        interval = _recovery_interval_sec()
        self._primary_retry_at = (
            time.monotonic() + interval if interval > 0 else None
        )

    def _primary_probe_due(self) -> bool:
        """주 커넥터 복귀 시도가 가능한 시점인지 확인한다."""
        return (
            self._primary_retry_at is not None
            and time.monotonic() >= self._primary_retry_at
        )

    async def _probe_primary(self, call: Callable[[], object]) -> object | None:
        """폴백 활성 상태에서 주 커넥터를 1회 시도한다.

        성공하면 회로를 닫고(주 커넥터 복귀) 결과를 반환한다.
        실패하면 다음 복귀 시도를 뒤로 미루고 None을 반환해 폴백 체인으로 진행시킨다.
        """
        try:
            result = await call()  # type: ignore[misc]
        except ConnectorError as exc:
            self._last_failure = str(exc)
            self._schedule_primary_probe()
            _LOG.warning(
                "%s: 주 커넥터 복귀 시도 실패 — 폴백 유지, 다음 시도 예약: %s",
                self.name,
                exc,
            )
            return None
        self._fallback_active = False
        self._failure_count = 0
        self._last_failure = ""
        self._primary_retry_at = None
        _LOG.info("%s: 주 커넥터(%s) 복귀 성공 — 회로 닫힘", self.name, self.primary_name)
        return result

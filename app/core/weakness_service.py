"""약점 프로필 갱신 서비스다.

UPSERT 기반: topic + subtopic + user_id 복합키 일치 시 frequency 증가,
미일치 시 신규 삽입. 두 경로(소크라테스, 과제 채점)에서 공용 호출한다.
asyncpg connection과 호환되는 WeaknessConnection Protocol을 통해 주입받는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class WeaknessConnection(Protocol):
    """asyncpg AsyncConnection과 호환되는 DB 연결 프로토콜이다."""

    async def fetchrow(
        self, query: str, *args: object
    ) -> Mapping[str, object] | None: ...

    async def fetch(
        self, query: str, *args: object
    ) -> list[Mapping[str, object]]: ...

    async def execute(self, query: str, *args: object) -> str: ...


@dataclass(frozen=True)
class WeaknessEntry:
    """약점 갱신 입력 단위다."""

    user_id: str
    topic: str
    subtopic: str
    error_pattern: str
    # 심각도 1~5 범위만 허용
    severity: int


def _new_profile_id() -> str:
    """weakness_profile 신규 id를 생성한다. wkp_ prefix + uuid4 hex이다."""
    return f"wkp_{uuid.uuid4().hex}"


# UPSERT SQL — PostgreSQL ON CONFLICT 문법 사용
# subtopic이 NULL이 아닌 경우에만 UniqueConstraint가 동작하므로 WHERE 절로 한정
_UPSERT_SQL = """
INSERT INTO weakness_profile
    (id, user_id, topic, subtopic, error_pattern, frequency, severity, first_seen_at, last_seen_at)
VALUES
    ($1, $2, $3, $4, $5, 1, $6, NOW(), NOW())
ON CONFLICT (user_id, topic, subtopic)
    WHERE subtopic IS NOT NULL
DO UPDATE SET
    frequency   = weakness_profile.frequency + 1,
    last_seen_at = NOW(),
    severity    = GREATEST(weakness_profile.severity, EXCLUDED.severity)
RETURNING id
"""


async def upsert_weakness(conn: WeaknessConnection, entry: WeaknessEntry) -> str:
    """단건 약점을 UPSERT한다.

    생성 또는 갱신된 weakness_profile id를 반환한다.
    기존 행이 있으면 frequency +1, last_seen_at 갱신, severity는 더 큰 값으로 갱신한다.
    """
    new_id = _new_profile_id()
    row = await conn.fetchrow(
        _UPSERT_SQL,
        new_id,
        entry.user_id,
        entry.topic,
        entry.subtopic,
        entry.error_pattern,
        entry.severity,
    )
    # RETURNING id가 반드시 반환되므로 None 방어
    if row is None:
        raise RuntimeError(f"weakness_profile UPSERT 실패: entry={entry}")
    returned_id = row.get("id") if hasattr(row, "get") else row["id"]
    return str(returned_id)


async def upsert_weaknesses(
    conn: WeaknessConnection,
    entries: list[WeaknessEntry],
) -> list[str]:
    """다건 약점을 일괄 UPSERT한다.

    각 항목을 순서대로 처리하고 생성/갱신된 id 목록을 반환한다.
    트랜잭션은 호출자가 관리한다.
    """
    ids: list[str] = []
    for entry in entries:
        profile_id = await upsert_weakness(conn, entry)
        ids.append(profile_id)
    return ids


_SELECT_UNRESOLVED_SQL = """
SELECT
    id, user_id, topic, subtopic, error_pattern,
    frequency, severity, first_seen_at, last_seen_at
FROM weakness_profile
WHERE user_id = $1
  AND resolved_at IS NULL
ORDER BY frequency DESC, last_seen_at DESC
"""


async def get_user_weaknesses(
    conn: WeaknessConnection,
    user_id: str,
) -> list[dict[str, object]]:
    """사용자의 미해결 약점 목록을 반환한다.

    resolved_at IS NULL 조건으로 아직 극복되지 않은 항목만 조회한다.
    frequency 내림차순, last_seen_at 내림차순으로 정렬한다.
    """
    rows = await conn.fetch(_SELECT_UNRESOLVED_SQL, user_id)
    return [dict(row) for row in rows]


_RESOLVE_SQL = """
UPDATE weakness_profile
SET resolved_at = NOW()
WHERE id = $1
"""


async def resolve_weakness(
    conn: WeaknessConnection,
    weakness_id: str,
) -> None:
    """약점을 극복 상태로 마킹한다.

    resolved_at을 현재 시각으로 설정한다.
    이미 resolved인 경우에도 멱등하게 갱신한다.
    """
    await conn.execute(_RESOLVE_SQL, weakness_id)

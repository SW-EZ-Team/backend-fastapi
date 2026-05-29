"""사용자 음성 프로필 DB CRUD 서비스다.

asyncpg 직접 SQL 방식을 사용하며 weakness_service.py 의 WeaknessConnection
Protocol 을 재사용해 연결을 주입받는다.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.weakness_service import WeaknessConnection


@dataclass(frozen=True)
class VoiceProfileRecord:
    """DB 에서 읽은 사용자 음성 프로필 레코드다."""

    id: str
    user_id: str
    name: str
    ref_audio_url: str
    ref_text: str
    language: str
    sample_rate: int
    duration_sec: float


def _new_profile_id() -> str:
    """voice_profile 신규 ID 를 생성한다. vpf_ prefix + uuid4 hex 이다."""
    return f"vpf_{uuid.uuid4().hex}"


# voice_profile 삽입 SQL — id 를 RETURNING 으로 확인
_INSERT_SQL = """
INSERT INTO voice_profile
    (id, user_id, name, ref_audio_url, ref_text, language, sample_rate, duration_sec, created_at)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
RETURNING id
"""

# 단건 조회 SQL
_SELECT_BY_ID_SQL = """
SELECT id, user_id, name, ref_audio_url, ref_text, language, sample_rate, duration_sec
FROM voice_profile
WHERE id = $1
"""

# 사용자별 전체 조회 SQL — 최신순 정렬
_SELECT_BY_USER_SQL = """
SELECT id, user_id, name, ref_audio_url, ref_text, language, sample_rate, duration_sec
FROM voice_profile
WHERE user_id = $1
ORDER BY created_at DESC
"""

# 삭제 SQL — user_id 까지 검증해 본인 프로필만 삭제 가능하게 한다
_DELETE_SQL = """
DELETE FROM voice_profile
WHERE id = $1 AND user_id = $2
RETURNING id
"""


def _row_to_record(row: Mapping[str, object]) -> VoiceProfileRecord:
    """DB 행 매핑을 VoiceProfileRecord 로 변환한다."""
    # Mapping 값은 object 이지만 asyncpg 가 DB 스키마 타입 그대로 반환함을 보장한다
    from typing import cast
    return VoiceProfileRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        ref_audio_url=str(row["ref_audio_url"]),
        ref_text=str(row["ref_text"]),
        language=str(row["language"]),
        sample_rate=cast(int, row["sample_rate"]),
        duration_sec=cast(float, row["duration_sec"]),
    )


async def create_voice_profile(
    conn: WeaknessConnection,
    user_id: str,
    name: str,
    ref_audio_url: str,
    ref_text: str,
    language: str,
    sample_rate: int,
    duration_sec: float,
    profile_id: str | None = None,
) -> str:
    """voice_profile 행을 삽입하고 생성된 ID 를 반환한다.

    profile_id 를 지정하면 해당 값을 사용하고, None 이면 자동 생성한다.
    """
    profile_id = profile_id or _new_profile_id()
    row = await conn.fetchrow(
        _INSERT_SQL,
        profile_id,
        user_id,
        name,
        ref_audio_url,
        ref_text,
        language,
        sample_rate,
        duration_sec,
    )
    if row is None:
        raise RuntimeError(f"voice_profile INSERT 실패: user_id={user_id}")
    return str(row["id"])


async def get_voice_profile(
    conn: WeaknessConnection,
    profile_id: str,
) -> VoiceProfileRecord | None:
    """profile_id 로 단건 조회한다. 없으면 None 을 반환한다."""
    row = await conn.fetchrow(_SELECT_BY_ID_SQL, profile_id)
    if row is None:
        return None
    return _row_to_record(row)


async def list_user_voice_profiles(
    conn: WeaknessConnection,
    user_id: str,
) -> list[VoiceProfileRecord]:
    """사용자의 모든 음성 프로필을 최신순으로 반환한다."""
    rows = await conn.fetch(_SELECT_BY_USER_SQL, user_id)
    return [_row_to_record(row) for row in rows]


async def delete_voice_profile(
    conn: WeaknessConnection,
    profile_id: str,
    user_id: str,
) -> bool:
    """본인 소유 프로필만 삭제하고 성공 여부를 반환한다."""
    row = await conn.fetchrow(_DELETE_SQL, profile_id, user_id)
    # RETURNING id 가 반환되면 삭제 성공
    return row is not None

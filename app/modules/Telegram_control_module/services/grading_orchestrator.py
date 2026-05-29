"""과제 채점 전체 흐름을 오케스트레이션한다.

파일 다운로드 → submission INSERT → VLM 채점 → submission UPDATE → 약점 갱신 → DM 회신
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.weakness_service import WeaknessConnection
from app.core.weakness_service import WeaknessEntry
from app.core.weakness_service import upsert_weaknesses

from ..config import get_default_bot_token
from ..schemas import TelegramMessageSummary
from . import file_downloader
from .assignment_grader import GradingResult
from .assignment_grader import grade_submission
from .telegram_client import TelegramClient

# 과제 조회 쿼리 — 해당 사용자의 가장 최근 미완료 과제를 찾는다
_FIND_ASSIGNMENT_SQL = """
SELECT a.id, a.prompt, a.criteria, a.difficulty_level, a.target_concepts
FROM assignment a
JOIN chapter ch ON ch.id = a.chapter_id
WHERE ch.course_id IN (
    SELECT course_id FROM curriculum WHERE user_id = $1
)
AND a.id NOT IN (SELECT assignment_id FROM submission WHERE user_id = $1 AND status = 'done')
ORDER BY a.created_at DESC LIMIT 1
"""

# 텔레그램 계정 ↔ user 매핑 조회
_FIND_USER_SQL = "SELECT user_id FROM telegram_account WHERE telegram_chat_id = $1"

# submission 상태 전이 쿼리
_INSERT_SUBMISSION_SQL = (
    "INSERT INTO submission (id, assignment_id, user_id, status, submission_source, submitted_at) "
    "VALUES ($1, $2, $3, 'grading', 'telegram', NOW())"
)
_UPDATE_DONE_SQL = (
    "UPDATE submission SET status='done', official_score=$1, "
    "official_feedback=$2, official_ai_confidence=$3 WHERE id=$4"
)
_UPDATE_FAILED_SQL = "UPDATE submission SET status='failed' WHERE id=$1"


def _new_submission_id() -> str:
    """sbm_ prefix + uuid4 hex로 submission id를 생성한다."""
    return f"sbm_{uuid.uuid4().hex}"


async def _find_user_id(conn: WeaknessConnection, chat_id: int) -> str | None:
    """telegram_chat_id로 연결된 user_id를 조회한다."""
    row = await conn.fetchrow(_FIND_USER_SQL, chat_id)
    if row is None:
        return None
    uid = row.get("user_id") if hasattr(row, "get") else row["user_id"]
    return str(uid) if uid else None


@dataclass(frozen=True)
class _AssignmentInfo:
    """채점에 필요한 과제 상세 정보다."""

    assignment_id: str
    title: str
    steps: list[str]
    rubric: list[str]


async def _find_assignment(conn: WeaknessConnection, user_id: str) -> _AssignmentInfo | None:
    """해당 사용자의 가장 최근 미완료 과제 정보를 조회한다."""
    row = await conn.fetchrow(_FIND_ASSIGNMENT_SQL, user_id)
    if row is None:
        return None
    aid = row.get("id") if hasattr(row, "get") else row["id"]
    if not aid:
        return None
    prompt = str(row.get("prompt") or "제출 과제") if hasattr(row, "get") else str(row["prompt"] or "제출 과제")
    criteria = row.get("criteria") if hasattr(row, "get") else row["criteria"]
    rubric = criteria if isinstance(criteria, list) else ["완성도", "정확성", "창의성"]
    return _AssignmentInfo(
        assignment_id=str(aid),
        title=prompt[:50] if len(prompt) > 50 else prompt,
        steps=[],
        rubric=rubric,
    )


async def _send_dm(client: TelegramClient, chat_id: int, message: str) -> None:
    """봇 토큰이 있을 때만 DM을 전송한다."""
    token = get_default_bot_token()
    if token is None:
        return
    await client.send_message(token=token, chat_id=str(chat_id), message=message)


async def _apply_weaknesses(
    conn: WeaknessConnection,
    result: GradingResult,
    user_id: str,
) -> None:
    """채점 결과의 약점 목록을 weakness_profile에 반영한다."""
    if not result.weaknesses:
        return
    entries = [
        WeaknessEntry(
            user_id=user_id,
            topic=w.topic,
            subtopic=w.subtopic,
            error_pattern=w.error_pattern,
            severity=w.severity,
        )
        for w in result.weaknesses
    ]
    await upsert_weaknesses(conn, entries)


def _format_result_message(result: GradingResult) -> str:
    """채점 결과를 사용자 친화적 DM 텍스트로 포맷한다."""
    lines = [
        f"채점 완료! 점수: {result.score}점",
        f"신뢰도: {result.confidence:.0%}",
        "",
        f"피드백: {result.feedback}",
    ]
    if result.error_type and result.error_type != "없음":
        lines.append(f"주요 오류 유형: {result.error_type}")
    if result.weaknesses:
        lines.append(f"발견된 약점: {len(result.weaknesses)}개")
    return "\n".join(lines)


async def handle_file_submission(
    summary: TelegramMessageSummary,
    file_id: str,
    file_name: str,
    client: TelegramClient,
    db_conn: WeaknessConnection,
) -> None:
    """과제 파일 제출 채점 전체 흐름을 실행한다."""
    chat_id = summary.telegram_chat_id
    await _send_dm(client, chat_id, "⏳ 과제를 채점하고 있습니다...")

    # 사용자·과제 조회 — 매핑이 없어도 채점은 계속 진행한다
    user_id = await _find_user_id(db_conn, chat_id)
    asg_info = await _find_assignment(db_conn, user_id) if user_id else None
    effective_user = user_id or str(chat_id)
    assignment_id = asg_info.assignment_id if asg_info else None

    submission_id = _new_submission_id()
    await db_conn.execute(
        _INSERT_SUBMISSION_SQL, submission_id, assignment_id, effective_user
    )

    token = get_default_bot_token()
    if token is None:
        await db_conn.execute(_UPDATE_FAILED_SQL, submission_id)
        await _send_dm(client, chat_id, "봇 토큰이 설정되지 않아 파일을 다운로드할 수 없습니다.")
        return

    # 과제 정보가 있으면 해당 기준으로, 없으면 범용 기준으로 채점한다
    title = asg_info.title if asg_info else "제출 과제"
    steps = asg_info.steps if asg_info else []
    rubric = asg_info.rubric if asg_info else ["완성도", "정확성", "창의성"]

    try:
        file_info = await file_downloader.get_file_info(token, file_id)
        file_bytes = await file_downloader.download_file_bytes(token, file_info.file_path)
        result = await grade_submission(
            file_bytes=file_bytes,
            file_name=file_name,
            assignment_title=title,
            assignment_steps=steps,
            assignment_rubric=rubric,
        )
    except Exception as exc:
        await db_conn.execute(_UPDATE_FAILED_SQL, submission_id)
        await _send_dm(client, chat_id, f"채점 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({exc})")
        return

    await db_conn.execute(
        _UPDATE_DONE_SQL,
        result.score,
        result.feedback,
        result.confidence,
        submission_id,
    )
    if user_id:
        await _apply_weaknesses(db_conn, result, user_id)

    await _send_dm(client, chat_id, _format_result_message(result))

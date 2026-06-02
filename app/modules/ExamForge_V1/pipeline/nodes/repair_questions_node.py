"""검증자의 fix_instructions를 소비해 실패 문항을 표적 교정하는 노드.

retry 경로의 1차 시도로 동작한다. 검증 실패 문항 중 구체적 수정 지시가 있는 것만
골라 blind 재생성 대신 '지적된 부분만' 고친다. 교정에 실패하거나 budget이 부족하면
기존 재생성(generate_questions) 폴백으로 그대로 넘어가 기존 동작을 보존한다.

정답 계약 불변 원칙:
- 모델이 돌려준 교정안에서 content 필드(stem/options/correct_answer/explanation/
  source_reference)만 원본 문항에 머지한다. question_id·draft_id·template_id 등 식별자와
  메타데이터는 절대 바꾸지 않는다 → 정답 인덱스/스키마 키/채점 계약 보존.
"""
from __future__ import annotations

import asyncio
import json
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.prompts.verification import REPAIR_SYSTEM, build_repair_prompt
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json
from app.modules.ExamForge_V1.common.config import (
    active_verifier_model,
    targeted_repair_enabled,
    verification_advisory_enabled,
    verification_concurrency,
    verifier_max_tokens,
)
from app.modules.ExamForge_V1.common.ai_bridge import (
    AIConnector,
    ChapterAIRequest,
    get_connector,
    get_current_budget,
)
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# 교정안에서 원본 문항으로 머지를 허용하는 content 필드 화이트리스트.
# 식별자/메타데이터는 여기에 없으므로 절대 덮어쓰이지 않는다.
_REPAIRABLE_FIELDS: tuple[str, ...] = (
    "stem", "options", "correct_answer", "explanation",
    "source_reference", "matching_pairs", "ordering_items",
    "blank_answers", "code_snippet",
)


def _normalize_fix_instructions(value: object) -> str:
    """검증 모델이 str/list/None 어느 타입을 줘도 교정 지시 문자열로 맞춘다."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return str(value).strip()


def _select_repair_targets(state: ExamForgeState) -> list[dict]:
    """fix_instructions가 있는 검증 실패 문항만 교정 대상으로 추린다."""
    failed_ids = set(state.get("failed_question_ids", []))
    targets: list[dict] = []
    for q in state.get("verified_questions", []):
        verification = q.get("_verification", {})
        if verification.get("passed", False):
            continue
        draft_id = q.get("draft_id", q.get("question_id", ""))
        if draft_id not in failed_ids:
            continue
        fix = _normalize_fix_instructions(verification.get("fix_instructions"))
        if not fix:
            # 구체 지시가 없으면 표적 교정 불가 → blind 재생성에 맡긴다.
            continue
        targets.append(q)
    return targets


def _merge_repaired(original: dict, repaired_data: dict) -> dict:
    """교정안의 content 필드만 원본에 머지한다 (식별자/메타데이터 보존)."""
    merged = original.copy()
    for key in _REPAIRABLE_FIELDS:
        if key in repaired_data and repaired_data[key] not in (None, "", []):
            merged[key] = repaired_data[key]
    # 교정 후에는 재검증을 강제하기 위해 이전 검증 결과를 제거한다.
    merged.pop("_verification", None)
    return merged


def route_after_repair(state: ExamForgeState) -> str:
    """교정 적용 여부에 따라 재검증/재생성 경로를 결정한다.

    - repair_applied=True  → "reverify"  : 교정된 문항을 verify_answers로 다시 검증
    - repair_applied=False → "regenerate": 기존 blind 재생성(generate_questions) 폴백
    """
    if state.get("pipeline_status") == "error":
        # 에러 상태는 재생성 경로의 즉시 반환 가드로 흡수시킨다.
        return "regenerate"
    return "reverify" if state.get("repair_applied", False) else "regenerate"


async def repair_questions_node(state: ExamForgeState) -> dict:
    """검증 실패 문항을 표적 교정한다. 성공 시 verify로 재진입하도록 신호를 남긴다."""
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: repair_questions_node")

    if state.get("verification_advisory") is True or verification_advisory_enabled():
        logger.warning("repair_questions_node: 검증 advisory 모드 — 표적 교정 생략")
        return {"repair_applied": False}

    # 안전 스위치: 끄면 즉시 blind 재생성 폴백 (변경 이전 동작과 동일).
    if not targeted_repair_enabled():
        logger.info("repair_questions_node: 표적 교정 비활성화 — 재생성 폴백")
        return {"repair_applied": False}

    targets = _select_repair_targets(state)
    if not targets:
        # 교정 대상 없음 → blind 재생성 폴백으로 라우팅.
        logger.info("repair_questions_node: 표적 교정 대상 없음 — 재생성 폴백")
        return {"repair_applied": False}

    budget = get_current_budget()
    if budget is not None and budget.exceeded:
        logger.warning("repair_questions_node: 예산 소진 — 재생성 폴백")
        return {"repair_applied": False}

    source_text = state.get("source_text", "")
    try:
        verifier = get_connector(active_verifier_model())
        semaphore = asyncio.Semaphore(verification_concurrency())
    except Exception as exc:
        logger.warning("repair 커넥터 초기화 실패: %s — 재생성 폴백", exc)
        return {"repair_applied": False}

    repaired_map = await _repair_all(targets, verifier, semaphore, source_text)
    if not repaired_map:
        logger.info("repair_questions_node: 교정 성공 0건 — 재생성 폴백")
        return {"repair_applied": False}

    # answered_questions를 교정안으로 교체해 verify_answers가 다시 검증하도록 한다.
    answered = state.get("answered_questions", [])
    new_answered = [repaired_map.get(q.get("question_id", ""), q) for q in answered]
    logger.info(
        "노드 완료: repair_questions_node (%.2fs) — %d건 교정",
        time.time() - node_start, len(repaired_map),
    )
    return {
        "answered_questions": new_answered,
        "repair_applied": True,
        "pipeline_status": "verifying",
    }


async def _repair_all(
    targets: list[dict],
    verifier: AIConnector,
    semaphore: asyncio.Semaphore,
    source_text: str,
) -> dict[str, dict]:
    """대상 문항을 병렬 교정하고 question_id → 교정 문항 매핑을 반환한다."""
    results = await asyncio.gather(
        *[_repair_one(q, verifier, semaphore, source_text) for q in targets],
        return_exceptions=True,
    )
    repaired_map: dict[str, dict] = {}
    for original, result in zip(targets, results):
        if isinstance(result, dict):
            repaired_map[original.get("question_id", "")] = result
        elif isinstance(result, BaseException):
            logger.warning("문항 교정 중 예외 — 해당 문항은 재생성으로 폴백: %s", result)
    return repaired_map


async def _repair_one(
    q: dict,
    verifier: AIConnector,
    semaphore: asyncio.Semaphore,
    source_text: str,
) -> dict | None:
    """단일 문항을 교정한다. 실패하면 None을 반환해 폴백을 유도한다."""
    async with semaphore:
        verification = q.get("_verification", {})
        fix = _normalize_fix_instructions(verification.get("fix_instructions"))
        issues = verification.get("issues", [])
        issues_text = "; ".join(str(i) for i in issues) if issues else "(상세 없음)"
        # 검증 메타데이터를 제거한 문항만 모델에 전달한다.
        clean_q = {k: v for k, v in q.items() if k != "_verification"}
        prompt = build_repair_prompt(
            question_json=json.dumps(clean_q, ensure_ascii=False, indent=2),
            fix_instructions=fix,
            issues_text=issues_text,
            source_excerpt=source_text[:2000],
        )
        # reasoning 모델이면 <think> 토큰 여유 확보, codex/claude면 2000 그대로(비용 불변)
        req = ChapterAIRequest(
            system=REPAIR_SYSTEM, user=prompt,
            max_tokens=verifier_max_tokens(2000), temperature=0.1,
        )
        try:
            resp = await verifier.generate(req)
            data = parse_llm_json(resp.text)
        except Exception as exc:
            logger.warning("문항 교정 호출/파싱 실패 — 폴백: %s", exc)
            return None
        if not isinstance(data, dict):
            logger.warning("문항 교정 응답이 dict가 아님 — 폴백")
            return None
        return _merge_repaired(q, data)

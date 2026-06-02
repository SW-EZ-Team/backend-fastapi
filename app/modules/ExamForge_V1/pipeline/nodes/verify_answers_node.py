"""교차 모델 정답 검증 노드."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json
from app.modules.ExamForge_V1.common.verification_status import (
    has_parse_failed_majority,
    is_genuine_fail,
    is_parse_failed,
    parse_failed_ratio,
)

import asyncio
import json
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.prompts.verification import VERIFICATION_SYSTEM, build_verification_prompt
from app.modules.ExamForge_V1.common.config import (
    active_verifier_model,
    verification_advisory_enabled,
    verification_concurrency,
    verifier_max_tokens,
)
from app.modules.ExamForge_V1.common.ai_bridge import get_connector, ChapterAIRequest
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)


async def verify_answers_node(state: ExamForgeState) -> dict:
    """생성된 정답을 다른 모델로 교차 검증한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환해 불필요한 AI 호출을 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: verify_answers_node")
    questions = state.get("answered_questions", [])
    if not questions:
        return {
            "verified_questions": [],
            "verification_failures": [],
            "pipeline_status": "error",
            "error_message": "검증 실패: 입력 문제 0건",
        }
    source_text = state.get("source_text", "")

    # 검증용 커넥터 (생성과 다른 모델 사용)
    try:
        verifier_name = active_verifier_model()
        verifier = get_connector(verifier_name)
        semaphore = asyncio.Semaphore(verification_concurrency())
    except Exception as exc:
        logger.error("검증 커넥터 초기화 실패: %s", exc)
        # 커넥터 초기화 실패는 파싱 문제가 아니라 인프라 장애이므로 기존 품질 게이트를 유지한다.
        verified = []
        for q in questions:
            q_copy = q.copy()
            q_copy["_verification"] = {"passed": False, "issues": [f"검증 커넥터 초기화 실패: {exc}"]}
            verified.append(q_copy)
        return {
            "verified_questions": verified,
            "verification_failures": [q.get("question_id", "") for q in questions],
            "pipeline_status": "validating",
        }

    async def _verify_one(q: dict) -> dict:
        """단일 문제를 교차 검증하고 _verification 필드를 추가한 문제를 반환한다."""
        async with semaphore:
            q_copy = q.copy()
            q_json = json.dumps(q_copy, ensure_ascii=False, indent=2)
            prompt = build_verification_prompt(
                question_json=q_json,
                source_excerpt=source_text[:2000],
            )
            req = ChapterAIRequest(
                system=VERIFICATION_SYSTEM,
                user=prompt,
                # reasoning 모델이면 <think> 토큰 여유 확보, codex/claude면 1000 그대로(비용 불변)
                max_tokens=verifier_max_tokens(1000),
                temperature=0.2,
            )
            try:
                resp = await verifier.generate(req)
            except Exception as exc:
                logger.warning("검증 커넥터 호출 실패: %s — 실패로 처리", exc)
                q_copy["_verification"] = {
                    "passed": False,
                    "issues": [f"검증 커넥터 호출 실패: {exc}"],
                }
                return q_copy
            try:
                result = parse_llm_json(resp.text)
                if not isinstance(result, dict):
                    raise ValueError("검증 응답이 dict가 아님")
                q_copy["_verification"] = _normalize_verification(result)
            except (ValueError, KeyError, TypeError) as exc:
                q_copy["_verification"] = _parse_failed_verification(exc)
            return q_copy

    raw_results = await asyncio.gather(
        *[_verify_one(q) for q in questions],
        return_exceptions=True,
    )

    verified: list[dict] = []
    # gather 반환값에서 결과를 수집해 공유 리스트 동시 접근 경쟁 조건 제거
    for i, r in enumerate(raw_results):
        if isinstance(r, dict):
            verified.append(r)
        else:
            # 예외 발생 시 묵묵히 통과시키면 품질 게이트가 무력화되므로 실패로 표시한다.
            # 검증 커넥터 장애는 재검증으로 처리해야 한다.
            fallback = questions[i].copy()
            fallback["_verification"] = {"passed": False, "issues": ["검증 커넥터 예외 발생 — 재검증 필요"]}
            verified.append(fallback)

    if has_parse_failed_majority(verified):
        logger.warning("검증 응답 파싱 실패 다수 감지 — parse_failed 문항 1회 재검증")
        retry_results = await asyncio.gather(
            *[_verify_one(questions[i]) for i, q in enumerate(verified) if is_parse_failed(q.get("_verification"))],
            return_exceptions=True,
        )
        _replace_parse_failed_results(verified, retry_results)
        if has_parse_failed_majority(verified):
            logger.warning(
                "검증기 응답 포맷 신뢰불가(parse_failed %.1f%%) — 파싱 실패는 advisory로 분리",
                parse_failed_ratio(verified) * 100,
            )

    # 실패 목록은 genuine fail만 담는다. parse_failed는 advisory라 재생성 실패율에 넣지 않는다.
    failures = [
        v.get("question_id", "")
        for v in verified
        if is_genuine_fail(v.get("_verification"))
    ]
    parse_ratio = parse_failed_ratio(verified)
    advisory_mode = verification_advisory_enabled()
    if advisory_mode and failures:
        logger.warning(
            "검증 advisory 모드 — 검증기 genuine fail %d건은 관측 로그로만 남긴다.",
            len(failures),
        )

    logger.info("노드 완료: verify_answers_node (%.2fs)", time.time() - node_start)
    return {
        "verified_questions": verified,
        "verification_failures": failures,
        "verification_parse_failed_count": sum(
            1 for q in verified if is_parse_failed(q.get("_verification"))
        ),
        "verification_parse_failed_ratio": parse_ratio,
        "verification_advisory": advisory_mode or (parse_ratio >= 0.5 and not failures),
        "pipeline_status": "validating",
    }


def _normalize_verification(result: dict) -> dict:
    """검증 응답 dict를 내부 계약에 맞게 정규화한다."""
    passed = result.get("passed")
    if not isinstance(passed, bool):
        raise ValueError("검증 응답 passed 불리언 누락")
    normalized = dict(result)
    issues = normalized.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]
    normalized["issues"] = [str(issue) for issue in issues]
    normalized["parse_failed"] = False
    return normalized


def _parse_failed_verification(exc: Exception) -> dict:
    """파싱 실패를 genuine fail이 아닌 별도 검증불가 상태로 표시한다."""
    return {
        "passed": None,
        "parse_failed": True,
        "issues": [f"검증 응답 파싱 실패 — advisory 재검증 필요: {exc}"],
    }


def _replace_parse_failed_results(verified: list[dict], retry_results: list[object]) -> None:
    """재검증 결과를 기존 parse_failed 위치에만 덮어쓴다."""
    retry_iter = iter(retry_results)
    for index, question in enumerate(verified):
        if not is_parse_failed(question.get("_verification")):
            continue
        result = next(retry_iter, None)
        if isinstance(result, dict):
            verified[index] = result

"""블룸 분류 분포를 보정하는 노드."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json

import json
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.quality.difficulty_scorer import score_bloom_distribution
from app.modules.ExamForge_V1.prompts.difficulty_calibration import (
    CALIBRATION_SYSTEM,
    build_calibration_prompt,
)
from app.modules.ExamForge_V1.common.ai_bridge import get_planner_connector, ChapterAIRequest
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.quality.cjk_sanitizer import sanitize_exam_questions

logger = get_logger(__name__)


async def calibrate_difficulty_node(state: ExamForgeState) -> dict:
    """문제의 난이도/블룸 레벨을 보정한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환해 불필요한 AI 호출을 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: calibrate_difficulty_node")
    questions = state.get("verified_questions", [])
    plan = state.get("exam_plan", {})
    target_bloom = plan.get("bloom_distribution", {})

    # 현재 분포 확인
    try:
        current_dist = score_bloom_distribution(questions)
    except Exception as exc:
        logger.warning("블룸 분포 계산 실패 — 보정 생략: %s", exc)
        return {
            "calibrated_questions": sanitize_exam_questions(questions),
            "pipeline_status": "formatting",
            "error_message": f"블룸 분포 계산 실패 — 난이도 보정 생략: {exc}",
        }

    # 목표 대비 불균형이 작으면 보정 생략
    if _is_balanced(current_dist, target_bloom):
        logger.info("노드 완료: calibrate_difficulty_node (%.2fs) → 보정 생략", time.time() - node_start)
        return {
            "calibrated_questions": sanitize_exam_questions(questions),
            "pipeline_status": "formatting",
        }

    # AI로 난이도 보정
    try:
        connector = get_planner_connector()
    except Exception as exc:
        logger.warning("난이도 보정 커넥터 초기화 실패 — 보정 생략: %s", exc)
        return {
            "calibrated_questions": sanitize_exam_questions(questions),
            "pipeline_status": "formatting",
            "error_message": f"난이도 보정 커넥터 초기화 실패 — 보정 생략: {exc}",
        }
    q_json = json.dumps(
        [{"question_id": q.get("question_id", ""),
          "stem": q.get("stem", "")[:100],
          "difficulty": q.get("difficulty"),
          "bloom_level": q.get("bloom_level", "")}
         for q in questions[:50]],
        ensure_ascii=False,
    )
    prompt = build_calibration_prompt(q_json)
    req = ChapterAIRequest(
        system=CALIBRATION_SYSTEM,
        user=prompt,
        max_tokens=3000,
        temperature=0.3,
    )
    try:
        resp = await connector.generate(req)
    except Exception as exc:
        # AI 커넥터 장애 시 보정 없이 원본 문제를 그대로 사용한다
        logger.warning("난이도 보정 AI 호출 실패 — 원본 유지: %s", exc)
        return {
            "calibrated_questions": sanitize_exam_questions(questions),
            "pipeline_status": "formatting",
            "error_message": f"난이도 보정 AI 호출 실패 — 원본 유지: {exc}",
        }

    # 파싱 오류 발생 시 추적할 변수 — None 이면 정상 처리
    calibration_error: str | None = None
    try:
        data = parse_llm_json(resp.text)
        # LLM이 calibrations 객체 대신 배열/스칼라/None을 줄 수 있다.
        # dict가 아니면 .get()이 AttributeError로 죽고(except 미포착) 정상 생성된
        # 시험 전체가 파이프라인 실패로 전환되므로, 비정상 타입은 보정 생략으로 흡수한다.
        if not isinstance(data, dict):
            raise ValueError(f"난이도 보정 응답이 dict가 아님: {type(data).__name__}")
        raw_calibrations = data.get("calibrations", [])
        # calibrations 항목 자체도 dict가 아닐 수 있으므로(예: 문자열 배열) dict만 추린다.
        calibrations = [c for c in raw_calibrations if isinstance(c, dict)] \
            if isinstance(raw_calibrations, list) else []
        cal_map = {c.get("question_id", ""): c for c in calibrations}
        calibrated: list[dict] = []
        for q in questions:
            q_copy = q.copy()
            q_id = q_copy.get("question_id", "")
            if q_id in cal_map:
                cal = cal_map[q_id]
                suggested_diff = cal.get("suggested_difficulty")
                if suggested_diff is not None:
                    q_copy["difficulty"] = suggested_diff
                suggested_bloom = cal.get("suggested_bloom")
                if suggested_bloom is not None:
                    q_copy["bloom_level"] = suggested_bloom
            calibrated.append(q_copy)
        questions = calibrated
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("난이도 보정 파싱 실패 — 원본 유지: %s", e)
        calibration_error = f"난이도 보정 파싱 실패 — 원본 유지: {e}"

    logger.info("노드 완료: calibrate_difficulty_node (%.2fs)", time.time() - node_start)
    result: dict = {
        "calibrated_questions": sanitize_exam_questions(questions),
        "pipeline_status": "formatting",
    }
    if calibration_error:
        result["error_message"] = calibration_error
    return result


def _is_balanced(
    current: dict[str, float],
    target: dict[str, float],
    tolerance: float = 0.15,
) -> bool:
    """목표 분포와 현재 분포가 허용 범위 내인지 확인한다."""
    if not target:
        return True
    for level, t_ratio in target.items():
        c_ratio = current.get(level, 0.0)
        if abs(c_ratio - t_ratio) > tolerance:
            return False
    return True

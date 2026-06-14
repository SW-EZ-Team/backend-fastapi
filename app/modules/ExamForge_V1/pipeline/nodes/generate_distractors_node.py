"""객관식 문제의 오답 선택지를 별도 생성하는 노드.

plan-first 변경 (D 요구사항):
- 사후 물리 이동(balance_correct_answer_positions/_move_correct_option) 제거.
  슬롯에 target_answer_position이 사전 배정됐으므로 이동이 필요 없다.
- 대신 생성된 정답 위치가 slot.target_answer_position과 일치하는지 검증한다.
- 불일치 시(AI가 위치를 틀리게 채운 경우)에만 1회 재배치(fallback)를 수행하고 로그에 기록한다.
- distractor 생성 자체(오답 보기 개선)는 그대로 유지한다.
"""
from __future__ import annotations

import asyncio
import time

from app.modules.ExamForge_V1.common.json_utils import parse_llm_json
from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.schemas.question import QuestionDraft
from app.modules.ExamForge_V1.templates.registry import get_template
from app.modules.ExamForge_V1.prompts.distractor_gen import get_distractor_system
from app.modules.ExamForge_V1.common.config import generation_concurrency, distractor_rewrite_enabled
from app.modules.ExamForge_V1.common.ai_bridge import (
    ChapterAIRequest,
    get_text_connector,
    run_connector_tasks,
)
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.quality.cjk_sanitizer import sanitize_exam_questions

logger = get_logger(__name__)

# 오답 생성이 필요한 MCQ 템플릿 ID 접두사
_MCQ_PREFIXES = ("ko_multiple_choice", "us_multiple_choice", "engineer_written", "cert_base")

# 5지선다 템플릿 목록 (문자열 매칭이 아닌 명시적 집합)
_FIVE_OPTION_TEMPLATES: frozenset[str] = frozenset([
    "ko_multiple_choice_5", "us_multiple_choice_5",
    "engineer_written", "cert_base",
])


async def generate_distractors_node(state: ExamForgeState) -> dict:
    """MCQ 문제의 오답 선택지를 문항 단위로 개선한다."""
    # 상위 노드에서 오류가 발생한 경우 즉시 반환해 오류 전파를 막는다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: generate_distractors_node")
    questions = state.get("questions", [])
    if not questions:
        return {
            "questions_with_distractors": [],
            "pipeline_status": "error",
            "error_message": "문제 생성 실패: 입력 문제 0건",
        }
    locale = state.get("locale", "ko")

    # MCQ가 아닌 문제는 그대로 통과
    mcq_questions: list[dict] = []
    non_mcq_questions: list[dict] = []
    for q in questions:
        if any(q.get("template_id", "").startswith(p) for p in _MCQ_PREFIXES):
            mcq_questions.append(q)
        else:
            non_mcq_questions.append(q)

    if not mcq_questions:
        # MCQ가 없으면 오답 생성 없이 다음 단계(정답/해설 생성)로 진행
        return {
            "questions_with_distractors": sanitize_exam_questions(questions),
            "pipeline_status": "answering",
        }

    try:
        semaphore = asyncio.Semaphore(generation_concurrency())
        connector = get_text_connector()
        system_prompt = get_distractor_system(locale)
        # 모델별 supports("cli") 휴리스틱 대신 명시 환경 플래그로 결정한다
        rewrite_disabled = not distractor_rewrite_enabled()
    except Exception as exc:
        logger.error("오답 생성 커넥터 초기화 실패: %s — 원본 유지", exc)
        return {
            "questions_with_distractors": questions,
            "pipeline_status": "answering",
            "error_message": f"오답 생성 커넥터 초기화 실패 — 원본 선택지 유지: {exc}",
        }

    async def _improve_distractors(q: dict) -> dict:
        async with semaphore:
            if rewrite_disabled or _has_code_heavy_options(q):
                q_copy = q.copy()
                q_copy.setdefault(
                    "distractor_rationale",
                    "초기 문항 생성 단계의 오답 선택지를 보존함",
                )
                return q_copy
            try:
                template = get_template(q.get("template_id", ""))
                draft = QuestionDraft(**q)
                num_opts = 5 if q.get("template_id", "") in _FIVE_OPTION_TEMPLATES else 4
                prompt = template.build_distractor_prompt(draft, num_opts)
            except Exception as exc:
                logger.warning("오답 생성 준비 실패: %s — 원본 유지", exc)
                return q.copy()

            if not prompt:
                return q.copy()

            req = ChapterAIRequest(
                system=system_prompt,
                user=prompt,
                max_tokens=2000,
                temperature=0.6,
            )
            try:
                resp = await connector.generate(req)
            except Exception as exc:
                logger.warning("오답 개선 AI 호출 실패: %s — 원본 유지", exc)
                return q.copy()
            # 원본 state를 변이시키지 않도록 복사본에 반영
            q_copy = q.copy()
            try:
                data = parse_llm_json(resp.text)
                # LLM이 객체 대신 배열/스칼라를 주면 .get()이 AttributeError로 죽는다.
                # (except 튜플 미포착 → gather 폴백으로 빠지지만 의도된 '원본 유지'
                #  경로가 아니므로 명시적으로 dict일 때만 반영하고 아니면 원본을 보존한다.)
                if isinstance(data, dict):
                    q_copy["options"] = data.get("options", q_copy.get("options"))
                    q_copy["distractor_rationale"] = data.get("distractor_rationale")
                else:
                    logger.warning(
                        "오답 개선 응답이 dict가 아님(%s) — 원본 선택지 유지",
                        type(data).__name__,
                    )
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("오답 개선 파싱 실패: %s", e)
            return q_copy

    task_factories = [
        lambda question=question: _improve_distractors(question)
        for question in mcq_questions
    ]
    results = await run_connector_tasks(task_factories, connector)

    improved: list[dict] = []
    for i, r in enumerate(results):
        if isinstance(r, dict):
            improved.append(r)
        else:
            # 예외 발생한 건은 원본 사용
            improved.append(mcq_questions[i])

    # plan-first D 요구사항:
    # 사후 물리 이동(balance_correct_answer_positions) 제거.
    # 대신 슬롯 계약과 실제 정답 위치를 검증하고 불일치 시에만 1회 fallback 재배치.
    verified_improved = _verify_and_align_positions(improved)

    all_questions = sanitize_exam_questions(verified_improved + non_mcq_questions)
    logger.info("노드 완료: generate_distractors_node (%.2fs)", time.time() - node_start)
    return {"questions_with_distractors": all_questions, "pipeline_status": "answering"}


def _verify_and_align_positions(questions: list[dict]) -> list[dict]:
    """슬롯 계약(target_answer_position)과 실제 정답 위치를 검증하고 불일치 시만 재배치한다.

    정상 경로: AI가 슬롯 계약대로 정답을 올바른 위치에 채움 → 이동 0.
    예외 경로: AI가 위치를 틀리게 채운 경우 → 1회 재배치(fallback) + 로그 경고.
    """
    result: list[dict] = []
    for q in questions:
        target_pos: int | None = q.get("target_answer_position")
        if target_pos is None:
            # 슬롯 계약이 없는 문항(블루프린트 미적용)은 그대로 통과
            result.append(q)
            continue

        options = q.get("options") or []
        if not _is_single_answer_mcq(options):
            result.append(q)
            continue

        actual_pos = _find_correct_position(options)
        if actual_pos == target_pos:
            # 정상 경로: AI가 계약대로 정답 위치를 채웠다
            result.append(q)
        else:
            # 예외 경로: AI가 위치를 틀리게 채운 경우 1회 재배치
            logger.warning(
                "plan-first 정답 위치 불일치 — draft_id=%s, "
                "expected=%d, actual=%d → fallback 재배치",
                q.get("draft_id", "?"), target_pos, actual_pos,
            )
            result.append(_move_correct_option(q, target_pos))
    return result


def _find_correct_position(options: list[dict]) -> int:
    """정답(is_correct=True)의 0-index 위치를 반환한다."""
    for idx, opt in enumerate(options):
        if opt.get("is_correct"):
            return idx
    return 0


def _is_single_answer_mcq(options: object) -> bool:
    """선택지가 있고 정답 표시가 정확히 하나인지 확인한다."""
    if not isinstance(options, list) or len(options) < 2:
        return False
    return sum(1 for option in options if option.get("is_correct")) == 1


def _move_correct_option(question: dict, target_index: int) -> dict:
    """정답 선택지를 목표 위치로 옮기고 label을 기존 순서 규칙에 맞춘다."""
    options = [option.copy() for option in question.get("options", [])]
    original_labels = [
        str(option.get("label", index + 1))
        for index, option in enumerate(options)
    ]
    current_index = next(
        (index for index, option in enumerate(options) if option.get("is_correct")),
        0,
    )
    correct_option = options.pop(current_index)
    options.insert(target_index, correct_option)
    for index, option in enumerate(options):
        option["label"] = original_labels[index]
    moved = question.copy()
    moved["options"] = options
    if moved.get("correct_answer"):
        moved["correct_answer"] = str(options[target_index].get("label", ""))
    return moved


def _has_code_heavy_options(question: dict) -> bool:
    """선택지에 코드가 많으면 오답 재작성으로 JSON이 깨질 위험이 높다."""
    for option in question.get("options") or []:
        text = str(option.get("text", ""))
        if "\n" in text or "fn " in text or "let " in text or "println!" in text:
            return True
    return False

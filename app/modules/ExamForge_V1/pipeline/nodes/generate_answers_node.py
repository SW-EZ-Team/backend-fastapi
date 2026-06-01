"""정답과 해설을 생성하는 노드."""
from __future__ import annotations

import asyncio
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.schemas.question import QuestionDraft
from app.modules.ExamForge_V1.templates.registry import get_template
from app.modules.ExamForge_V1.prompts.answer_gen import get_answer_system
from app.modules.ExamForge_V1.common.config import generation_concurrency
from app.modules.ExamForge_V1.common.ai_bridge import (
    ChapterAIRequest,
    get_text_connector,
    run_connector_tasks,
)
from app.modules.ExamForge_V1.common.errors import ParseError
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)


async def generate_answers_node(state: ExamForgeState) -> dict:
    """각 문제의 정답과 해설을 문항 단위로 생성한다."""
    # 상위 노드에서 오류가 발생한 경우 즉시 반환해 오류 전파를 막는다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: generate_answers_node")
    questions = state.get("questions_with_distractors", [])
    if not questions:
        return {
            "answered_questions": [],
            "pipeline_status": "error",
            "error_message": "정답 생성 실패: 입력 문제 0건",
        }
    source_text = state.get("source_text", "")
    locale = state.get("locale", "ko")

    try:
        semaphore = asyncio.Semaphore(generation_concurrency())
        connector = get_text_connector()
        system_prompt = get_answer_system(locale)
    except Exception as exc:
        logger.error("정답 생성 커넥터 초기화 실패: %s", exc)
        return {
            "answered_questions": [],
            "pipeline_status": "error",
            "error_message": f"정답 생성 커넥터 초기화 실패: {exc}",
        }

    async def _generate_answer(q: dict) -> dict:
        async with semaphore:
            # 템플릿·드래프트 준비 — 실패 시 빈 정답으로 즉시 반환
            try:
                template = get_template(q.get("template_id", ""))
                draft = QuestionDraft(**q)
                prompt = template.build_answer_prompt(draft, source_text)
            except Exception as exc:
                logger.warning("정답 생성 템플릿/드래프트 준비 실패: %s", exc)
                return _empty_answer(q)

            for attempt in range(3):
                req = _build_answer_request(system_prompt, prompt, attempt)
                try:
                    resp = await connector.generate(req)
                except Exception as exc:
                    logger.warning("정답 생성 커넥터 오류(%d차): %s", attempt + 1, exc)
                    continue
                try:
                    answered = template.parse_answer_response(resp.text, draft)
                    data = answered.model_dump()
                    if _has_answer_payload(data):
                        return _preserve_generation_fields(data, q)
                except (ParseError, ValueError, KeyError, TypeError) as e:
                    logger.warning("정답 생성 실패(%d차): %s", attempt + 1, e)
            return _empty_answer(q)

    task_factories = [
        lambda question=question: _generate_answer(question)
        for question in questions
    ]
    results = await run_connector_tasks(task_factories, connector)

    answered: list[dict] = []
    for i, r in enumerate(results):
        if isinstance(r, dict):
            answered.append(r)
        else:
            # 예외 시 원본 데이터에 빈 정답 추가
            answered.append(_empty_answer(questions[i]))

    logger.info("노드 완료: generate_answers_node (%.2fs)", time.time() - node_start)
    return {
        "answered_questions": answered,
        "pipeline_status": "verifying",
    }


def _build_answer_request(
    system_prompt: str,
    prompt: str,
    attempt: int,
) -> ChapterAIRequest:
    """정답 생성 요청을 만든다. 재시도는 JSON 안정성을 우선한다."""
    json_guard = (
        "\n\n[JSON 안정성 규칙]\n"
        "- JSON 객체 하나만 출력하시오.\n"
        "- 마크다운, 코드블록, 백틱, 원본 코드 줄 복붙을 금지한다.\n"
        "- 코드가 필요한 설명은 자연어로 요약하고 큰따옴표가 든 코드 조각을 직접 쓰지 마시오.\n"
        "- 객관식 explanation은 정답 근거와 모든 오답별 오개념을 포함해 350~900자로 완결하시오."
    )
    repair_suffix = json_guard
    if attempt == 1:
        repair_suffix += (
            "\n\n[재생성 지시]\n"
            "- JSON 객체 하나만 출력하시오.\n"
            "- correct_answer, explanation, source_reference를 반드시 채우시오.\n"
            "- 문자열은 닫는 따옴표까지 완전한 JSON으로 출력하시오.\n"
            "- explanation은 마크다운 없이 자연어 문단으로 작성하시오."
        )
    elif attempt == 2:
        repair_suffix += (
            "\n\n[최소 JSON 재생성]\n"
            "{\"correct_answer\":\"정답\",\"explanation\":\"핵심 근거\","
            "\"source_reference\":\"근거 문장\"} 형식만 출력하시오."
        )
    return ChapterAIRequest(
        system=system_prompt,
        user=prompt + repair_suffix,
        max_tokens=6000 if attempt > 0 else 3500,
        temperature=0.05 if attempt > 0 else 0.3,
    )


def _has_answer_payload(question: dict) -> bool:
    """정답/해설 필수 필드가 채워졌는지 확인한다."""
    return bool(question.get("correct_answer") and question.get("explanation"))


def _empty_answer(q: dict) -> dict:
    """정답 생성 실패 시 구조 검증에서 걸릴 빈 답안을 만든다."""
    fallback = q.copy()
    fallback["correct_answer"] = ""
    fallback["explanation"] = ""
    fallback["question_id"] = fallback.get("draft_id", "")
    return fallback


def _preserve_generation_fields(answered: dict, draft: dict) -> dict:
    """정답 생성 전 단계에서 보강된 필드를 보존한다."""
    preserved = answered.copy()
    for key in (
        "distractor_rationale", "code_snippet", "_blueprint_slot",
        "_chapter", "_concept_key", "_reasoning_type",
    ):
        if draft.get(key) and not preserved.get(key):
            preserved[key] = draft[key]
    return preserved

"""객관식 문제의 오답 선택지를 별도 생성하는 노드."""
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
        # MCQ 가 없으면 오답 생성 없이 다음 단계(정답/해설 생성)로 진행
        return {"questions_with_distractors": questions, "pipeline_status": "answering"}

    try:
        semaphore = asyncio.Semaphore(generation_concurrency())
        connector = get_text_connector()
        system_prompt = get_distractor_system(locale)
        # 모델별 supports("cli") 휴리스틱(감사 A-2: gemini만 스킵되던 문제) 대신
        # 명시 환경 플래그로 오답 재작성 켜짐/꺼짐을 결정한다.
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
                q_copy["options"] = data.get("options", q_copy.get("options"))
                q_copy["distractor_rationale"] = data.get("distractor_rationale")
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

    all_questions = improved + non_mcq_questions
    logger.info("노드 완료: generate_distractors_node (%.2fs)", time.time() - node_start)
    return {"questions_with_distractors": all_questions, "pipeline_status": "answering"}


def _has_code_heavy_options(question: dict) -> bool:
    """선택지에 코드가 많으면 오답 재작성으로 JSON이 깨질 위험이 높다."""
    for option in question.get("options") or []:
        text = str(option.get("text", ""))
        if "\n" in text or "fn " in text or "let " in text or "println!" in text:
            return True
    return False

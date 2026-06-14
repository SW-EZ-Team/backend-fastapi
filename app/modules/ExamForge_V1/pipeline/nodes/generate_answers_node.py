"""정답과 해설을 생성하는 노드."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.schemas.question import QuestionDraft
from app.modules.ExamForge_V1.templates.registry import get_template
from app.modules.ExamForge_V1.prompts.answer_gen import get_answer_system
from app.modules.ExamForge_V1.common.config import generation_concurrency
from app.modules.ExamForge_V1.common.ai_bridge import (
    ChapterAIRequest,
    get_text_connector,
    run_connector_tasks,
    set_allow_reserve,
    allow_reserve_budget,
)
from app.modules.ExamForge_V1.common.errors import ParseError
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.quality.cjk_sanitizer import sanitize_exam_question

logger = get_logger(__name__)

# codex 경로: output-schema 파일로 응답 형식을 강제해 파싱 실패를 줄인다.
# 스키마 파일이 없으면 no-op (기존 동작 유지)
_CODEX_ANSWER_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "common" / "codex_answer_gen.schema.json"
)


def _codex_schema_extra() -> dict[str, str]:
    """codex 커넥터에 정답 생성용 output-schema 경로를 전달한다.

    스키마 파일이 존재할 때만 extra에 포함한다. Anthropic/Gemini 커넥터는
    output_schema_path를 무시하므로 다른 경로에서 no-op이다.
    """
    if _CODEX_ANSWER_SCHEMA_PATH.exists():
        return {"output_schema_path": str(_CODEX_ANSWER_SCHEMA_PATH)}
    return {}


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

            # 마지막으로 성공한 응답 텍스트를 추적한다.
            # 3회 호출이 모두 예외(예: 400)면 None으로 남아 regex fallback을 건너뛴다.
            # (None 미초기화 시 'resp' unbound 크래시를 방지한다.)
            last_resp_text: str | None = None

            for attempt in range(3):
                req = _build_answer_request(system_prompt, prompt, attempt)
                try:
                    resp = await connector.generate(req)
                except Exception as exc:
                    logger.warning("정답 생성 커넥터 오류(%d차): %s", attempt + 1, exc)
                    continue
                last_resp_text = resp.text
                try:
                    answered = template.parse_answer_response(resp.text, draft)
                    data = answered.model_dump()
                    if _has_answer_payload(data):
                        return sanitize_exam_question(_preserve_generation_fields(data, q))
                except (ParseError, ValueError, KeyError, TypeError) as e:
                    logger.warning(
                        "정답 생성 실패(%d차): %s\n응답(앞300): %.300s",
                        attempt + 1, e, resp.text,
                    )

            # 3회 모두 실패 — 응답 텍스트가 있으면 최후 수단으로 regex 파싱 시도
            if last_resp_text is not None:
                try:
                    extracted = _extract_answer_by_regex(last_resp_text, draft)
                    if extracted and _has_answer_payload(extracted):
                        logger.info("정답 생성 regex fallback 성공: draft_id=%s", q.get("draft_id"))
                        return sanitize_exam_question(_preserve_generation_fields(extracted, q))
                except Exception as exc:
                    logger.warning("정답 생성 regex fallback 실패: %s", exc)
            else:
                logger.error("정답 생성 3회 모두 커넥터 예외 — 응답 없음: draft_id=%s", q.get("draft_id"))
            logger.error("정답 생성 3회 모두 실패 — 빈 정답 반환: draft_id=%s", q.get("draft_id"))
            return _empty_answer(q)

    task_factories = [
        lambda question=question: _generate_answer(question)
        for question in questions
    ]
    # 해설 생성 구간 동안 reserve 예산 사용을 허용한다(핵심 산출물 보호).
    # upstream 재시도가 일반 예산을 소진했어도 해설은 예약된 풀로 생성된다.
    reserve_token = set_allow_reserve(True)
    try:
        results = await run_connector_tasks(task_factories, connector)
    finally:
        allow_reserve_budget.reset(reserve_token)

    answered: list[dict] = []
    for i, r in enumerate(results):
        if isinstance(r, dict):
            answered.append(r)
        else:
            # 예외 시 원본 데이터에 빈 정답 추가
            answered.append(_empty_answer(questions[i]))

    # 파이프라인 불변식 검증: question_id 또는 template_id가 비어 있는 문항을 걸러낸다.
    # 보충/보수 경로에서 유실된 식별자가 Spring 콜백까지 전파되는 것을 차단한다.
    valid_answered: list[dict] = []
    for q in answered:
        missing: list[str] = []
        if not q.get("question_id"):
            missing.append("question_id")
        if not q.get("template_id"):
            missing.append("template_id")
        if missing:
            logger.error(
                "generate_answers_node: %s 누락 문항 제거 — draft_id=%s, template_id=%s",
                "+".join(missing),
                q.get("draft_id", "(없음)"),
                q.get("template_id", "(없음)"),
            )
            continue
        valid_answered.append(q)
    answered = valid_answered

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
    """정답 생성 요청을 만든다. codex 경로는 output-schema를 적용해 파싱 안정성을 높인다."""
    json_guard = (
        "\n\n[JSON 안정성 규칙]\n"
        "- JSON 객체 하나만 출력하시오.\n"
        "- 마크다운, 코드블록, 백틱, 원본 코드 줄 복붙을 금지한다.\n"
        "- 코드가 필요한 설명은 자연어로 요약하고 큰따옴표가 든 코드 조각을 직접 쓰지 마시오.\n"
        # 길이 채우기 금지 — 짧고 통찰 있는 해설을 요구한다(전제 재진술 대신 원리 설명).
        "- 객관식 explanation은 ①정답 근거(원리, 1~2문장) ②가장 함정인 오답 1~2개의 오개념(괄호, 1문장) "
        "③takeaway(1문장)로 간결히 완결하시오. 전제·보기 텍스트 재진술과 글자수 채우기를 금지한다.\n"
        "- OX/단답 explanation은 정답 근거 1문장 + 핵심 오해 1문장으로 더 짧게 완결하시오."
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
        extra=_codex_schema_extra(),
    )


def _has_answer_payload(question: dict) -> bool:
    """정답/해설 필수 필드가 채워졌는지 확인한다."""
    return bool(question.get("correct_answer") and question.get("explanation"))


def _extract_answer_by_regex(text: str, draft: QuestionDraft) -> dict | None:
    """JSON 파싱 실패 시 정규식으로 correct_answer와 explanation을 직접 추출한다.

    Qwen3/LLM이 explanation 내부에 이스케이프되지 않은 큰따옴표(코드 예시 등)를
    넣어 JSON 파싱이 실패할 때 최후 수단으로 호출된다.

    추출 전략:
    1. correct_answer: 짧은 값이므로 단순 패턴으로 안전하게 추출
    2. explanation: 다음 JSON 키 패턴(\", \"fieldname\":) 까지의 구간을 추출
       (내부 큰따옴표가 있어도 다음 키 이름 패턴은 깨지지 않음)
    3. source_reference: 있으면 추출, 없으면 빈 문자열
    """
    import re
    import uuid

    # correct_answer 추출 — 짧은 값(숫자/영문 기호)이므로 단순 패턴으로 충분
    ca_match = re.search(r'"correct_answer"\s*:\s*"([^"]{1,50})"', text, re.IGNORECASE)
    if not ca_match:
        return None
    correct_answer = ca_match.group(1).strip()
    if not correct_answer:
        return None

    # explanation 추출 — 내부 큰따옴표가 있을 수 있으므로 다음 키까지 구간 추출
    explanation = _extract_field_to_next_key(text, "explanation")
    if not explanation:
        return None

    # source_reference 추출 (선택)
    source_reference = _extract_field_to_next_key(text, "source_reference") or ""

    return {
        "question_id": f"q_{uuid.uuid4().hex[:8]}",
        "draft_id": draft.draft_id,
        "template_id": draft.template_id,
        "topic": draft.topic,
        "difficulty": draft.difficulty,
        "bloom_level": draft.bloom_level or "",
        "stem": draft.stem,
        "options": [o.model_dump() for o in (draft.options or [])],
        "code_snippet": draft.code_snippet,
        "correct_answer": correct_answer,
        "explanation": explanation,
        "source_reference": source_reference,
    }


def _extract_field_to_next_key(text: str, field: str) -> str:
    """JSON 텍스트에서 fieldname 값을 다음 JSON 키까지 구간으로 추출한다.

    내부 이스케이프되지 않은 큰따옴표가 있어도 다음 JSON 키 패턴이 나오기 전까지
    문자를 수집해 값을 복원한다.
    """
    import re
    start_match = re.search(rf'"{re.escape(field)}"\s*:\s*"', text)
    if not start_match:
        return ""
    start = start_match.end()
    # 다음 JSON 키 패턴: ", "somekey": 또는 "somekey": (JSON 종료 직전)
    end_match = re.search(r'"\s*,\s*"[a-zA-Z_][a-zA-Z0-9_]*"\s*:', text[start:])
    if end_match:
        raw_value = text[start : start + end_match.start()]
    else:
        # 마지막 필드: 닫는 } 앞의 마지막 " 까지
        last_quote = text.rfind('"', start)
        raw_value = text[start : last_quote] if last_quote > start else text[start:]
    return raw_value.strip()


def _empty_answer(q: dict) -> dict:
    """정답 생성 실패 시 구조 검증에서 걸릴 빈 답안을 만든다.

    question_id 보장 원칙:
    - 항상 고유한 UUID 기반 question_id를 새로 발급한다.
    - draft_id를 question_id로 재사용하면 동일 draft_id를 가진 문항이
      repair_questions_node의 repaired_map 키 충돌을 일으킬 수 있다.
    - template_id도 원본 q에서 보존하므로 빈 template_id는 전파되지 않는다.
    """
    import uuid
    fallback = q.copy()
    fallback["correct_answer"] = ""
    fallback["explanation"] = ""
    # draft_id 기반 재사용 대신 항상 신규 UUID 발급 — 키 충돌 방지
    fallback["question_id"] = f"q_{uuid.uuid4().hex[:8]}"
    return sanitize_exam_question(fallback)


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

"""MLX 로컬 모델을 사용해 시각 슬라이드를 생성하는 추론 모듈."""
from __future__ import annotations

import asyncio
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, cast

from app.modules.ChapterStudio_V1.app.visual_demo_types import VisualPreviewResponse

# ── 모델 상수 ──
_MODEL_ID = "unsloth/Qwen3.6-35B-A3B-UD-MLX-4bit"
_MAX_TOKENS = 6144
_TEMPERATURE = 0.4

# ── 스레드 안전 싱글톤 + 단일 스레드 실행기 ──
_model_lock = threading.Lock()
_model_cache: tuple[Any, Any] | None = None
_inference_executor = ThreadPoolExecutor(max_workers=1)

# ── 시스템 프롬프트 — JSON 스키마 포함 ──
_SYSTEM_PROMPT = """당신은 교육용 시각 슬라이드를 JSON으로 생성하는 전문가입니다.
주어진 주제에 대해 4~5개의 시각 슬라이드와 3~5개의 노트 블록을 생성하세요.
반드시 아래 JSON 스키마를 정확히 따르고, 마크다운 펜스 없이 순수 JSON만 출력하세요.

응답 최상위 형식:
{
  "topic": "주제 문자열",
  "visual_slides": [...],
  "note_blocks": [{"tag": "태그", "body": "본문"}]
}

각 슬라이드 형식:
{"slide_idx":0,"title":"슬라이드 제목","visual_type":"<타입>","visual_spec":{"spec_type":"<타입>",...},"voice_script":"100~200자 한국어 강의 나레이션"}
지원 타입과 spec 스키마:
1. flowchart — {"spec_type":"flowchart","nodes":[{"id":"A","label":"레이블","x":0,"y":0}],"edges":[{"from":"A","to":"B"}]}
   ※ 엣지 키는 반드시 "from" (from_id 아님)
2. bar_chart — {"spec_type":"bar_chart","title":"차트제목","x_label":"X","y_label":"Y","data":[{"label":"항목","value":80,"color":"#207B4C"}]}
3. concept_map — {"spec_type":"concept_map","nodes":[{"id":"center","label":"중심","size":48}],"edges":[{"from":"center","to":"n1"}]}
   ※ 엣지 키는 반드시 "from" (from_id 아님)
4. mermaid — {"spec_type":"mermaid","diagram_type":"flowchart","code":"graph LR\\nA-->B"}
5. timeline — {"spec_type":"timeline","events":[{"year":"2024","event":"이벤트명","detail":"상세설명"}]}
6. table — {"spec_type":"table","title":"표제목","headers":["열1","열2"],"rows":[["값1","값2"]]}
   ※ 모든 행의 열 수가 headers 열 수와 반드시 일치해야 함
7. radar_chart — {"spec_type":"radar_chart","axes":["축1","축2","축3"],"datasets":[{"label":"L","values":[50,80,60],"color":"#207B4C"}]}
   ※ 모든 데이터셋의 values 길이가 axes 길이와 반드시 일치해야 함
8. tree — {"spec_type":"tree","root":{"label":"루트","children":[{"label":"자식","children":[]}]}}
9. comparison — {"spec_type":"comparison","left":{"title":"좌측제목","points":["항목1"]},"right":{"title":"우측제목","points":["항목1"]}}
규칙:
- visual_type과 visual_spec.spec_type은 반드시 동일한 값이어야 함
- voice_script는 100~200자 자연스러운 한국어 강의 나레이션
- 주제에 가장 적합한 4~5종 타입을 골라 사용 (9종 모두 사용할 필요 없음)
- JSON에 위 스키마에 정의된 필드 이외의 키를 추가하지 마세요
- 순수 JSON만 출력, 마크다운 펜스(```) 사용 금지
"""
def _load_model() -> tuple[Any, Any]:
    """mlx_lm 모델과 토크나이저를 로드한다. 이중 검사 잠금으로 스레드 안전 보장."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    with _model_lock:
        if _model_cache is not None:
            return _model_cache
        import mlx_lm
        _model_cache = cast(tuple[Any, Any], mlx_lm.load(_MODEL_ID))
        return _model_cache

def _build_prompt(topic: str) -> str:
    """주제를 받아 채팅 템플릿 형식의 프롬프트 문자열을 반환한다."""
    _, tokenizer = _load_model()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"주제: {topic}\n\n위 주제에 대한 시각 슬라이드 JSON을 생성하세요."},
    ]
    # 채팅 템플릿 적용 — Qwen3 토크나이저가 지원하는 경우 사용
    if hasattr(tokenizer, "apply_chat_template"):
        return cast(
            str,
            tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,  # Qwen3 Jinja2 템플릿이 <think> 블록을 억제하도록 설정
            ),
        )
    # 폴백: 단순 텍스트 조합
    return f"<|im_start|>system\n{_SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n주제: {topic}\n\n위 주제에 대한 시각 슬라이드 JSON을 생성하세요.<|im_end|>\n<|im_start|>assistant\n"


def _extract_json(raw: str) -> str:
    """LLM 출력 문자열에서 JSON 부분만 추출한다. 중괄호 깊이 추적으로 정확히 잘라낸다."""
    # thinking 블록 제거 — 닫히지 않은 블록도 처리
    stripped = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    stripped = re.sub(r"<think>.*", "", stripped, flags=re.DOTALL)
    # 마크다운 코드 펜스 제거
    stripped = re.sub(r"```(?:json)?", "", stripped).strip()
    # 중괄호 깊이 추적으로 최상위 JSON 객체 추출
    start = stripped.find("{")
    if start == -1:
        return stripped
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start:i + 1]
    # 닫히지 않은 JSON — 가능한 범위까지 반환
    return stripped[start:]

def _run_inference(topic: str, max_tokens: int, temperature: float = _TEMPERATURE) -> str:
    """동기 mlx_lm.generate 호출로 LLM 출력 문자열을 반환한다."""
    import mlx_lm
    try:
        from mlx_lm.sample_utils import make_sampler
    except ImportError:
        # mlx_lm 내부 API 경로 변경 시 기본 샘플러 사용
        sampler = None
    else:
        sampler = make_sampler(temp=temperature, top_p=0.9, min_p=0.05)
    model, tokenizer = _load_model()
    prompt = _build_prompt(topic)
    return mlx_lm.generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=max_tokens,
        sampler=sampler,
        verbose=False,
    )


def _parse_response(raw: str, topic: str) -> VisualPreviewResponse:
    """LLM 출력을 파싱해 VisualPreviewResponse를 반환한다."""
    json_str = _extract_json(raw)
    data = json.loads(json_str)
    # topic 필드 보정 — LLM이 다른 값을 넣은 경우 덮어씀
    data["topic"] = topic
    return VisualPreviewResponse.model_validate(data)


async def generate_visual_preview(topic: str) -> VisualPreviewResponse:
    """주어진 주제에 대한 시각 슬라이드 응답을 LLM으로 생성한다.
    단일 스레드 실행기로 동시 추론 충돌을 방지하고, 타임아웃/파싱 실패 시 1회 재시도한다.
    """
    # 라우터 외부 호출 경로 방어 — FastAPI Query 검증을 우회한 경우 대비
    if not topic or len(topic) > 80:
        raise ValueError(f"주제는 1~80자여야 합니다 (입력: {len(topic) if topic else 0}자)")

    loop = asyncio.get_running_loop()

    # 1차 시도
    try:
        raw = await asyncio.wait_for(
            loop.run_in_executor(_inference_executor, _run_inference, topic, _MAX_TOKENS),
            timeout=180,
        )
    except asyncio.TimeoutError:
        raw = None

    if raw is not None:
        try:
            return _parse_response(raw, topic)
        except (json.JSONDecodeError, ValueError):
            pass

    # 2차 재시도 — 슬라이드 수를 줄이고 temperature를 낮춰 결정적 출력 유도
    retry_topic = f"{topic} (슬라이드 2개, 노트 3개로 간소화)"
    try:
        raw2 = await asyncio.wait_for(
            loop.run_in_executor(
                _inference_executor,
                partial(_run_inference, retry_topic, _MAX_TOKENS, 0.3),
            ),
            timeout=180,
        )
    except asyncio.TimeoutError:
        raise ValueError("LLM 추론이 제한 시간(180초)을 2회 연속 초과했습니다")

    try:
        return _parse_response(raw2, topic)
    except (json.JSONDecodeError, ValueError) as exc:
        # 2회 연속 파싱 실패 — 상위 호출자가 500 대신 의미 있는 오류를 받도록 명시적으로 재발생
        msg = f"LLM이 유효한 JSON을 2회 연속 생성하지 못했습니다: {exc}"
        raise ValueError(msg) from exc

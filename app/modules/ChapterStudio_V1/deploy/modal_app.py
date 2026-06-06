from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

import modal
# requests는 Modal 컨테이너 내부에서만 설치되는 패키지다(deploy/image에 uv_pip_install 선언).
# 로컬 ChapterStudio_V1 환경에는 직접 의존성이 없으므로 pyproject.toml의
# mypy.overrides(requests.*)에서 프로젝트 수준으로 import 허용을 선언한다.
import requests

APP_NAME = os.environ.get("CHAPTERSTUDIO_MODAL_APP_NAME", "chapterstudio-qwen27b")
MODEL_ID = os.environ.get("CHAPTERSTUDIO_MODAL_MODEL_ID", "Qwen/Qwen3.6-27B-FP8")
MODEL_ALIAS = os.environ.get("CHAPTERSTUDIO_MODAL_MODEL_ALIAS", APP_NAME)
MAX_MODEL_LEN = os.environ.get("CHAPTERSTUDIO_MODAL_MAX_MODEL_LEN", "131072")
MAX_NUM_BATCHED_TOKENS = os.environ.get("CHAPTERSTUDIO_MODAL_MAX_NUM_BATCHED_TOKENS", "32768")
LANGUAGE_MODEL_ONLY = os.environ.get("CHAPTERSTUDIO_MODAL_LANGUAGE_MODEL_ONLY") == "1"
VLLM_PORT = 8000
MINUTES = 60


def response_schema(slide_count: int = 5) -> dict[str, Any]:
    """강의 슬라이드 수에 맞춘 vLLM guided JSON 스키마를 만든다."""
    bounded_count = max(5, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["slides", "quizzes", "note_blocks", "assignment", "voice_scripts"],
        "properties": {
            "slides": {
                "type": "array",
                "minItems": bounded_count,
                "maxItems": bounded_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["slide_idx", "title", "focus", "checkpoint", "category", "html", "css"],
                    "properties": {
                        "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
                        "title": {"type": "string", "minLength": 1, "maxLength": 48},
                        "focus": {"type": "string", "minLength": 1, "maxLength": 160},
                        "checkpoint": {"type": "string", "minLength": 1, "maxLength": 200},
                        "category": {"type": "string", "enum": ["text", "diagram", "code", "math", "chart", "interactive", "table"]},
                        "html": {"type": "string", "minLength": 1, "maxLength": 5600},
                        "css": {"type": "string", "maxLength": 1400},
                    },
                },
            },
            "quizzes": {
                "type": "array",
                "minItems": bounded_count,
                "maxItems": bounded_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["slide_idx", "question", "choices", "answer_idx", "difficulty", "explanation"],
                    "properties": {
                        "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
                        "question": {"type": "string", "minLength": 1, "maxLength": 180},
                        "choices": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 4,
                            "items": {"type": "string", "minLength": 1, "maxLength": 60},
                        },
                        "answer_idx": {"type": "integer", "minimum": 0, "maximum": 3},
                        "difficulty": {
                            "type": "string",
                            "enum": ["기억", "이해", "적용", "함정 교정", "실전 판단", "오해"],
                        },
                        # Pydantic GeneratedQuiz.explanation(min_length=30)과 정합화한 품질 하한.
                        "explanation": {"type": "string", "minLength": 30, "maxLength": 720},
                    },
                },
            },
            "note_blocks": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["heading", "bullets"],
                    "properties": {
                        "heading": {"type": "string", "minLength": 1, "maxLength": 30},
                        "bullets": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "string", "minLength": 1, "maxLength": 220},
                        },
                    },
                },
            },
            "assignment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "assignment_format", "expected_minutes", "steps", "rubric"],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 60},
                    "assignment_format": {"type": "string", "minLength": 2, "maxLength": 80},
                    "expected_minutes": {"type": "integer", "minimum": 20, "maximum": 40},
                    "steps": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 5,
                        "items": {"type": "string", "minLength": 1, "maxLength": 220},
                    },
                    "rubric": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 5,
                        "items": {"type": "string", "minLength": 1, "maxLength": 220},
                    },
                },
            },
            "voice_scripts": {
                "type": "array",
                "minItems": bounded_count,
                "maxItems": bounded_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["slide_idx", "script_text"],
                    "properties": {
                        "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
                        # Pydantic GeneratedVoiceScript.script_text(min_length=40)과 정합화한 품질 하한.
                        # 본격 목표(900~1600자)는 self-check + targeted-repair가 채운다.
                        "script_text": {"type": "string", "minLength": 40, "maxLength": 2400},
                    },
                },
            },
        },
    }


# slides visual.type 전체 허용 집합 — plan이 좁히기 전 기본값(union).
_SLIDES_VISUAL_TYPE_ENUM_FULL = [
    "number_line",
    "comparison",
    "comparison-table",
    "step_flow",
    "flow-strip",
    "fraction_bar",
    "concept_map",
    "example_box",
    "metric-card",
]


def slides_schema(
    slide_count: int = 5,
    plan_visual_types: list[str] | None = None,
) -> dict[str, Any]:
    """구조화 visual 슬라이드 배열만 생성하는 작은 guided JSON 스키마다.

    Qwen은 raw HTML을 만들지 않고 visual.type/data만 만든다. Python 렌더러가 이 구조를
    검증된 SVG/HTML body로 바꾸므로, 깨진 마크업이 iframe까지 전파되지 않는다.

    [plan-first 강제 범위 — 정직한 한계 명시]
    xgrammar(guided_decoding_backend)는 JSON Schema의 prefixItems(위치별 다른 enum, 즉
    slide i의 visual.type을 그 슬롯의 단일 plan 값으로 못박기)를 신뢰성 있게 지원하지 않는다.
    배열은 단일 uniform `items` 스키마로만 제약된다. 따라서 이 스키마는:
      - plan_visual_types가 주어지면 enum을 "plan이 실제 쓰는 type 집합"으로 좁힌다
        (전체 9-enum 자유선택 → plan이 쓰는 3~5종으로 축소). 이는 schema가 지원하는 정직한
        narrowing이며, AI가 plan에 없는 type을 만드는 것을 생성시점에 차단한다.
      - 그러나 "slide i = 정확히 plan_vt_i 단일값"의 per-slot 강제는 schema가 못 한다.
        그 강제의 유일한 진실 소스는 parse_slides의 _enforce_plan_visual_type(universal backstop)다.
        schema가 per-slot 강제를 하는 척하지 않는다 — backstop이 책임진다.
    plan_visual_types=None이면 전체 union enum으로 폴백한다(레거시·미주입 경로 호환).
    """
    bounded_count = max(5, min(15, slide_count))
    visual_type_enum = _resolve_visual_type_enum(plan_visual_types)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["slides"],
        "properties": {
            "slides": {
                "type": "array",
                "minItems": bounded_count,
                "maxItems": bounded_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["slide_idx", "title", "category", "narration", "visual", "checkpoint"],
                    "properties": {
                        "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
                        "title": {"type": "string", "minLength": 1, "maxLength": 48},
                        "category": {"type": "string", "enum": ["text", "diagram", "math", "chart"]},
                        "narration": {"type": "string", "minLength": 20, "maxLength": 220},
                        "checkpoint": {"type": "string", "minLength": 1, "maxLength": 200},
                        "visual": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "data"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": visual_type_enum,
                                },
                                "data": {"type": "object", "additionalProperties": True},
                            },
                        },
                    },
                },
            }
        },
    }


def _resolve_visual_type_enum(plan_visual_types: list[str] | None) -> list[str]:
    """plan이 실제 쓰는 visual.type 집합으로 enum을 좁힌다(순서·중복 정리).

    plan_visual_types가 비었거나 None이면 전체 union enum으로 폴백한다.
    좁힐 때는 full enum의 순서를 보존해 결정적 출력을 만든다(xgrammar 캐시 안정).
    """
    if not plan_visual_types:
        return list(_SLIDES_VISUAL_TYPE_ENUM_FULL)
    used = set(plan_visual_types)
    narrowed = [vt for vt in _SLIDES_VISUAL_TYPE_ENUM_FULL if vt in used]
    # plan에 full enum 밖 값이 있으면(이론상 없어야 함) 그대로 뒤에 붙여 schema 유효성을 지킨다.
    extras = [vt for vt in plan_visual_types if vt not in _SLIDES_VISUAL_TYPE_ENUM_FULL]
    seen: set[str] = set()
    ordered_extras = [vt for vt in extras if not (vt in seen or seen.add(vt))]
    result = narrowed + ordered_extras
    return result or list(_SLIDES_VISUAL_TYPE_ENUM_FULL)


def quizzes_schema(slide_count: int = 5) -> dict[str, Any]:
    """퀴즈 배열만 생성하는 작은 guided JSON 스키마다(컴포넌트 병렬 생성용).

    정확히 slide_count개를 강제하며, item 구조는 lesson 스키마의 quiz 정의를 재사용한다.
    """
    bounded_count = max(5, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["quizzes"],
        "properties": {"quizzes": response_schema(bounded_count)["properties"]["quizzes"]},
    }


def note_schema(slide_count: int = 5) -> dict[str, Any]:
    """note_blocks(정확히 4개/각 bullets 3개)만 생성하는 작은 guided JSON 스키마다."""
    bounded_count = max(5, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["note_blocks"],
        "properties": {"note_blocks": response_schema(bounded_count)["properties"]["note_blocks"]},
    }


def assignment_schema(slide_count: int = 5) -> dict[str, Any]:
    """assignment 객체만 생성하는 작은 guided JSON 스키마다(steps/rubric은 반드시 배열).

    Qwen이 큰 스키마에서 rubric을 dict로 내던 실측 오류를 작은 단일목적 스키마로 강제해
    방지한다. steps/rubric은 lesson 스키마와 동일하게 string 배열로 고정한다.
    """
    bounded_count = max(5, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["assignment"],
        "properties": {"assignment": response_schema(bounded_count)["properties"]["assignment"]},
    }


# plan-first 섹션 role 순서·길이 상한 — config.VOICE_SECTION_RANGES와 정합해야 한다.
# modal_app은 deploy 독립 파일이라 app 패키지를 import하지 않으므로 값을 미러링한다.
# 정합성은 test_voice_modal_schema_alignment가 강제한다(불일치 시 FAIL).
# guided maxLength는 config의 max에 자연어 여유(80자)를 더해 모델 절단을 막되,
# 실제 슬롯 범위 강제는 결정적 슬롯 길이 게이트(voice_length_gate)가 담당한다.
_VOICE_SECTION_ORDER = ("intro", "core", "example", "closing")
_VOICE_SECTION_MAXLEN = {"intro": 280, "core": 780, "example": 530, "closing": 330}


def voice_script_schema(slide_count: int = 15) -> dict[str, Any]:
    """슬라이드별 TTS 대본 재호출에 쓰는 plan-first 섹션 guided JSON 스키마다.

    sections 배열(정확히 4항목)을 guided decoding으로 강제해 Modal/Qwen 경로에서도
    plan-first 구조가 생성시점에 보장되게 한다. role은 enum으로, 순서는 minItems/maxItems
    4 고정 + parse_voice 검증으로 맞춘다. script_text는 sections에서 파생되므로 guided
    required에서 제외한다(프롬프트 parallel_prompt_text.voice_prompt가 요구하는 최상위 키
    {slide_idx, sections}와 정확히 일치).
    """
    bounded_count = max(1, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["slide_idx", "sections"],
        "properties": {
            "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
            "sections": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["role", "text"],
                    "properties": {
                        "role": {"type": "string", "enum": list(_VOICE_SECTION_ORDER)},
                        # 섹션 하한은 슬롯 게이트가 결정적으로 강제하므로 guided엔 보수적 하한만 둔다.
                        "text": {"type": "string", "minLength": 10, "maxLength": 800},
                    },
                },
            },
        },
    }


def voice_segment_schema(slide_count: int = 15) -> dict[str, Any]:
    """긴 TTS 대본을 문단 단위로 병렬 재작성할 때 쓰는 guided JSON 스키마다."""
    bounded_count = max(1, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["slide_idx", "segment_idx", "segment_text"],
        "properties": {
            "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
            "segment_idx": {"type": "integer", "minimum": 0, "maximum": 3},
            "segment_text": {"type": "string", "minLength": 180, "maxLength": 600},
        },
    }


def supporting_materials_schema(slide_count: int = 15) -> dict[str, Any]:
    """퀴즈와 과제만 재호출할 때 쓰는 작은 guided JSON 스키마다."""
    bounded_count = max(5, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["quizzes", "assignment"],
        "properties": {
            "quizzes": response_schema(bounded_count)["properties"]["quizzes"],
            "assignment": response_schema(bounded_count)["properties"]["assignment"],
        },
    }


# schema_kind → 작은 단일목적 guided JSON 스키마 빌더 매핑.
# 컴포넌트 병렬 생성 경로(slides/quizzes/note/assignment)는 작은 스키마를 써서 xgrammar가
# 배열 개수·타입을 확실히 강제하게 한다. lesson/supporting_materials/voice 계열은 기존 유지.
_SCHEMA_BUILDERS: dict[str, Any] = {
    "slides": slides_schema,
    "quizzes": quizzes_schema,
    "note": note_schema,
    "assignment": assignment_schema,
    "voice_script": voice_script_schema,
    "voice_segment": voice_segment_schema,
    "supporting_materials": supporting_materials_schema,
}


def _select_guided_schema(
    schema_kind: str,
    slide_count: int,
    plan_visual_types: list[str] | None = None,
) -> dict[str, Any]:
    """schema_kind에 맞는 guided JSON 스키마를 고른다(미지정/lesson은 전체 lesson 스키마).

    slides 경로에서 plan_visual_types가 주어지면 visual.type enum을 plan 집합으로 좁힌다
    (slides_schema 참조 — per-slot 강제는 parse_slides backstop, schema는 집합 narrowing만).
    """
    if schema_kind == "slides":
        return slides_schema(slide_count, plan_visual_types)
    builder = _SCHEMA_BUILDERS.get(schema_kind)
    if builder is None:
        return response_schema(slide_count)
    return builder(slide_count)


def _extract_plan_visual_types(extra: dict[str, Any] | None) -> list[str] | None:
    """extra에서 plan_visual_types를 꺼낸다(콤마 결합 문자열 → 리스트).

    extra 값은 스칼라(str|int|float|bool)만 허용되므로 plan이 쓰는 visual.type 집합을
    콤마로 결합한 문자열로 전달받는다. 미존재·빈값이면 None(전체 enum 폴백).
    """
    if not extra:
        return None
    raw = extra.get("plan_visual_types")
    if not isinstance(raw, str) or not raw.strip():
        return None
    types = [t.strip() for t in raw.split(",") if t.strip()]
    return types or None


RESPONSE_SCHEMA: dict[str, Any] = response_schema()

app = modal.App(APP_NAME)

hf_cache = modal.Volume.from_name(f"{APP_NAME}-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name(f"{APP_NAME}-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-devel-ubuntu22.04",
        add_python="3.12",
    )
    .entrypoint([])
    .uv_pip_install(
        "vllm==0.19.1",
        "huggingface-hub[hf-transfer]==0.36.0",
        "requests==2.33.1",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "CHAPTERSTUDIO_MODAL_APP_NAME": APP_NAME,
            "CHAPTERSTUDIO_MODAL_MODEL_ID": MODEL_ID,
            "CHAPTERSTUDIO_MODAL_MODEL_ALIAS": MODEL_ALIAS,
            "CHAPTERSTUDIO_MODAL_MAX_MODEL_LEN": MAX_MODEL_LEN,
            "CHAPTERSTUDIO_MODAL_MAX_NUM_BATCHED_TOKENS": MAX_NUM_BATCHED_TOKENS,
            "CHAPTERSTUDIO_MODAL_LANGUAGE_MODEL_ONLY": "1" if LANGUAGE_MODEL_ONLY else "0",
        }
    )
)


@app.cls(
    image=image,
    gpu="B200:1",
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },
    timeout=30 * MINUTES,
    # 서버리스 idle 비용 최소화 — 작업 완료 후(또는 커넥터 shutdown() 후) 빠르게 컨테이너를
    # 회수하도록 짧게 둔다. 환경변수로 조절 가능(기본 30초).
    scaledown_window=int(os.environ.get("CHAPTERSTUDIO_MODAL_SCALEDOWN_SEC", "30")),
)
@modal.concurrent(max_inputs=8)
class Qwen27BServer:
    """Modal B200에서 Qwen3.6-27B-FP8 vLLM 서버를 띄우는 원격 클래스다."""

    @modal.enter()
    def start(self) -> None:
        cmd = [
            "vllm",
            "serve",
            MODEL_ID,
            "--served-model-name",
            MODEL_ALIAS,
            "--host",
            "0.0.0.0",
            "--port",
            str(VLLM_PORT),
            "--uvicorn-log-level",
            "warning",
            "--tensor-parallel-size",
            "1",
            "--gpu-memory-utilization",
            "0.92",
            "--max-model-len",
            MAX_MODEL_LEN,
            "--max-num-seqs",
            "8",
            "--max-num-batched-tokens",
            MAX_NUM_BATCHED_TOKENS,
            "--limit-mm-per-prompt",
            json.dumps({"image": 0, "video": 0, "audio": 0}),
        ]
        if LANGUAGE_MODEL_ONLY:
            cmd.append("--language-model-only")
        self.vllm_proc = subprocess.Popen(cmd)
        self._wait_ready()

    @modal.exit()
    def stop(self) -> None:
        proc = getattr(self, "vllm_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    @modal.method()
    def healthz(self) -> dict[str, Any]:
        return {"status": "ok", "model": MODEL_ID, "served_model": MODEL_ALIAS}

    @modal.method()
    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        extra: dict[str, str | int | float | bool] | None = None,
    ) -> dict[str, Any]:
        seed = int(extra.get("seed", 7)) if extra is not None else 7
        slide_count = int(extra.get("slide_count", 5)) if extra is not None else 5
        schema_kind = str(extra.get("schema", "lesson")) if extra is not None else "lesson"
        plan_visual_types = _extract_plan_visual_types(extra)
        return self._chat(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            slide_count=slide_count,
            schema_kind=schema_kind,
            plan_visual_types=plan_visual_types,
        )

    @modal.method()
    def generate_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            self._chat(
                system=str(item.get("system", "")),
                user=str(item["user"]),
                max_tokens=int(item.get("max_tokens", 4096)),
                temperature=float(item.get("temperature", 0.2)),
                seed=int(dict(item.get("extra", {})).get("seed", 7)),
                slide_count=int(dict(item.get("extra", {})).get("slide_count", 5)),
                schema_kind=str(dict(item.get("extra", {})).get("schema", "lesson")),
                plan_visual_types=_extract_plan_visual_types(dict(item.get("extra", {}))),
            )
            for item in batch
        ]

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + 25 * MINUTES
        url = f"http://127.0.0.1:{VLLM_PORT}/health"
        while time.monotonic() < deadline:
            if self.vllm_proc.poll() is not None:
                raise RuntimeError(f"vLLM exited early with code {self.vllm_proc.returncode}")
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(5)
        raise TimeoutError("vLLM health check timed out")

    def _chat(self, system: str, user: str, max_tokens: int, temperature: float, seed: int, slide_count: int, schema_kind: str, plan_visual_types: list[str] | None = None) -> dict[str, Any]:
        guided_schema = _select_guided_schema(schema_kind, slide_count, plan_visual_types)
        payload: dict[str, Any] = {
            "model": MODEL_ALIAS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
            "seed": seed,
            "chat_template_kwargs": {"enable_thinking": False},
            "guided_json": guided_schema,
            "guided_decoding_backend": "xgrammar",
            "stop": ["</s>", "<|im_end|>"],
        }
        response = requests.post(
            f"http://127.0.0.1:{VLLM_PORT}/v1/chat/completions",
            json=payload,
            timeout=25 * MINUTES,
        )
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return {
            "text": choice["message"]["content"],
            "model": MODEL_ID,
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
            "finish_reason": str(choice.get("finish_reason", "unknown")),
        }

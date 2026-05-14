from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

import modal
import requests  # type: ignore[import-untyped]

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
                        "explanation": {"type": "string", "minLength": 1, "maxLength": 720},
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
                        "script_text": {"type": "string", "minLength": 1, "maxLength": 2400},
                    },
                },
            },
        },
    }


def voice_script_schema(slide_count: int = 15) -> dict[str, Any]:
    """슬라이드별 TTS 대본 재호출에 쓰는 작은 guided JSON 스키마다."""
    bounded_count = max(1, min(15, slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["slide_idx", "script_text"],
        "properties": {
            "slide_idx": {"type": "integer", "minimum": 0, "maximum": bounded_count - 1},
            "script_text": {"type": "string", "minLength": 850, "maxLength": 2400},
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
    scaledown_window=2 * MINUTES,
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
        return self._chat(system=system, user=user, max_tokens=max_tokens, temperature=temperature, seed=seed, slide_count=slide_count, schema_kind=schema_kind)

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

    def _chat(self, system: str, user: str, max_tokens: int, temperature: float, seed: int, slide_count: int, schema_kind: str) -> dict[str, Any]:
        if schema_kind == "voice_script":
            guided_schema = voice_script_schema(slide_count)
        elif schema_kind == "voice_segment":
            guided_schema = voice_segment_schema(slide_count)
        elif schema_kind == "supporting_materials":
            guided_schema = supporting_materials_schema(slide_count)
        else:
            guided_schema = response_schema(slide_count)
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

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import modal
import requests

APP_NAME = os.environ.get("KANANA_MODAL_APP_NAME", "kanana2-typofix")
MODEL_ID = os.environ.get(
    "KANANA_MODAL_MODEL_ID",
    "NotoriousH2/kanana-2-30b-a3b-instruct-2601-awq-w4a16",
)
MODEL_ALIAS = os.environ.get("KANANA_MODAL_MODEL_ALIAS", APP_NAME)
MAX_MODEL_LEN = os.environ.get("KANANA_MODAL_MAX_MODEL_LEN", "8192")
VLLM_PORT = 8000
MINUTES = 60

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
            "KANANA_MODAL_APP_NAME": APP_NAME,
            "KANANA_MODAL_MODEL_ID": MODEL_ID,
            "KANANA_MODAL_MODEL_ALIAS": MODEL_ALIAS,
            "KANANA_MODAL_MAX_MODEL_LEN": MAX_MODEL_LEN,
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
    scaledown_window=int(os.environ.get("KANANA_MODAL_SCALEDOWN_SEC", "30")),
)
@modal.concurrent(max_inputs=8)
class Kanana2Server:
    """Kanana2 오타수정 전용 vLLM 서버를 Modal B200에서 실행한다."""

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
            "0.9",
            "--max-model-len",
            MAX_MODEL_LEN,
            "--quantization",
            "compressed-tensors",
            "--trust-remote-code",
        ]
        self.vllm_proc = subprocess.Popen(cmd)
        self._wait_ready()

    @modal.exit()
    def stop(self) -> None:
        proc = getattr(self, "vllm_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    @modal.method()
    def correct(self, text: str, instruction: str) -> str:
        """OpenAI 호환 chat/completions로 교정 본문만 반환한다."""
        payload: dict[str, Any] = {
            "model": MODEL_ALIAS,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": text},
            ],
            "max_tokens": _max_tokens_for_text(text),
            "temperature": 0.0,
            "top_p": 0.9,
            "chat_template_kwargs": {"enable_thinking": False},
            "stop": ["</s>", "<|im_end|>"],
        }
        response = requests.post(
            f"http://127.0.0.1:{VLLM_PORT}/v1/chat/completions",
            json=payload,
            timeout=10 * MINUTES,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

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


def _max_tokens_for_text(text: str) -> int:
    """입력 길이만큼 다시 쓸 여유를 두되 8k 컨텍스트 안에서 폭주를 막는다."""
    return max(256, min(4096, len(text) + 512))

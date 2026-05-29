"""로컬 Mac MLX Qwen3.6-35B-A3B 텍스트 생성 커넥터.

개발 중 AI API 비용을 절약하기 위해 로컬 MLX 모델을 사용한다.
프로덕션 전환 시 ACTIVE_TEXT_MODEL 또는 AI_MODEL 환경변수 하나만 바꾸면
이 커넥터를 교체할 수 있다.

환경변수:
    MLX_QWEN3_MODEL_PATH: MLX 모델 디렉터리 경로
        미설정 시 HF 캐시에서 자동 탐색한다.
"""
from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from pathlib import Path

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import (
    ChapterAIRequest,
    ChapterAIResponse,
)

_LOG = logging.getLogger(__name__)

# HF 캐시 내 unsloth 배포 모델 식별자 — MLX_QWEN3_MODEL_PATH 미설정 시 사용
_HF_REPO_ID = "unsloth/Qwen3.6-35B-A3B-UD-MLX-4bit"
_HF_CACHE_KEY = "models--unsloth--Qwen3.6-35B-A3B-UD-MLX-4bit"

# 생성 기본값
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMP = 0.7


def _resolve_model_path() -> str:
    """환경변수 또는 HF 캐시에서 MLX 모델 경로를 결정한다."""
    explicit = os.environ.get("MLX_QWEN3_MODEL_PATH", "").strip()
    if explicit:
        return explicit

    # HF 캐시 표준 위치 두 곳을 순서대로 탐색한다
    hf_home = os.environ.get("HF_HOME", "")
    candidates: list[Path] = []
    if hf_home:
        candidates.append(Path(hf_home) / "hub" / _HF_CACHE_KEY)
    candidates.append(Path.home() / ".cache" / "huggingface" / "hub" / _HF_CACHE_KEY)

    for base in candidates:
        snapshots_dir = base / "snapshots"
        if snapshots_dir.exists():
            # 가장 최근 스냅샷 디렉터리를 선택한다
            snaps = sorted(snapshots_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            if snaps:
                return str(snaps[0])

    # 경로를 찾지 못하면 HF hub에서 다운로드 후 경로를 반환한다
    _LOG.info("MLX 모델 로컬 캐시 없음 — HF에서 다운로드: %s", _HF_REPO_ID)
    return _HF_REPO_ID


@lru_cache(maxsize=1)
def _load_model() -> tuple[object, object]:
    """모델과 토크나이저를 최초 호출 시 한 번만 로드한다."""
    try:
        import mlx_lm  # noqa: PLC0415 — MLX는 로드 시점에만 임포트한다
    except ImportError as exc:
        raise ConnectorError(
            "mlx-lm 패키지가 설치되지 않았다. "
            "'.venv/bin/pip install mlx-lm' 또는 'uv pip install mlx-lm'으로 설치하라."
        ) from exc

    model_path = _resolve_model_path()
    _LOG.info("MLX Qwen3 모델 로드 시작: %s", model_path)
    model, tokenizer = mlx_lm.load(model_path)
    _LOG.info("MLX Qwen3 모델 로드 완료")
    return model, tokenizer


def _build_prompt(system: str, user: str, tokenizer: object) -> str:
    """system·user 메시지를 chat template으로 변환한다."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    apply_fn = getattr(tokenizer, "apply_chat_template", None)
    if callable(apply_fn):
        return apply_fn(messages, tokenize=False, add_generation_prompt=True)
    # chat template이 없으면 단순 텍스트로 조합한다
    prefix = f"System: {system}\n\n" if system else ""
    return f"{prefix}User: {user}\nAssistant:"


def _count_tokens(tokenizer: object, text: str) -> int:
    """토큰 수를 추정한다 — 정확한 값이 없으면 공백 기반 근사값을 반환한다."""
    encode_fn = getattr(tokenizer, "encode", None)
    if callable(encode_fn):
        ids = encode_fn(text)
        return len(ids) if isinstance(ids, list) else len(text) // 4
    return len(text) // 4


class MlxQwen3LocalConnector:
    """로컬 MLX Qwen3.6-35B-A3B 텍스트 생성 커넥터.

    개발 환경 전용이며 모델은 첫 generate 호출 시 지연 로드된다.
    프로덕션에서는 ACTIVE_TEXT_MODEL=claude_sonnet 으로 교체한다.
    """

    name = "mlx_qwen3_local"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """MLX 모델로 텍스트를 생성하고 공통 응답 스키마로 반환한다."""
        # MLX는 동기 CPU-bound 작업이므로 이벤트 루프 블로킹을 막기 위해 스레드풀에서 실행한다
        return await asyncio.get_event_loop().run_in_executor(
            None, self._generate_sync, req
        )

    def _generate_sync(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """동기 컨텍스트에서 MLX 추론을 수행한다."""
        try:
            import mlx_lm  # noqa: PLC0415
            from mlx_lm.sample_utils import make_sampler  # noqa: PLC0415
        except ImportError as exc:
            raise ConnectorError("mlx-lm 임포트 실패: mlx-lm 설치 여부를 확인하라.") from exc

        model, tokenizer = _load_model()
        prompt = _build_prompt(req.system, req.user, tokenizer)
        input_tokens = _count_tokens(tokenizer, prompt)

        max_tokens = req.max_tokens if req.max_tokens > 0 else _DEFAULT_MAX_TOKENS
        # temperature는 2.0 이상이면 1.0으로 클램핑한다 — MLX sampler 범위 제한
        temp = min(req.temperature, 1.0) if req.temperature > 0.0 else _DEFAULT_TEMP

        sampler = make_sampler(temp=temp)
        raw_text = mlx_lm.generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
        )

        output_tokens = _count_tokens(tokenizer, raw_text)
        return ChapterAIResponse(
            text=raw_text,
            model=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="stop",
        )

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """배치 요청을 순차 처리한다 — MLX는 GPU 메모리 경합을 막기 위해 직렬 실행한다."""
        results: list[ChapterAIResponse] = []
        for req in reqs:
            results.append(await self.generate(req))
        return results

    def supports(self, feature: str) -> bool:
        """로컬 MLX 모델이 지원하는 capability를 반환한다."""
        return feature in {"local", "mlx", "batch"}

"""Kanana MLX 기반 OCR 후처리 PostprocConnector 구현.

probe 단계에서 검증된 kanana-1.5-2.1b-instruct-2505-mlx (CER 16→0.22, 할루시네이션 0%,
페이지 단일 라인 평균 1.3초) 를 기반으로 한다. 파일명은 kanana2_* 로 통일해
향후 정식 Kanana-2 MLX 4bit 가 공개되면 .env 의 KANANA_MLX_MODEL_PATH 한 줄만
수정해 같은 슬롯으로 승격 가능하다.

역할: 한국어 맞춤법 교정 + LaTeX 수식 정규화 (preserve_latex=True 일 때 수식
블록을 플레이스홀더로 마스킹해 LLM 이 건드리지 못하게 한 뒤 원본 복원).

호출 규약 (단일):
 - base.PostprocConnector: refine(PostprocRequest) -> PostprocResponse

SRP: 이 파일은 'Manager' 레벨 (3단계 파이프라인 조립).
 - _kanana2_runtime: 모델 로드/추론
 - _kanana2_prompt:  프롬프트 + LaTeX 보호
 - _kanana2_diff:    결과 정제 + diff + 할루시네이션 판정
"""
from __future__ import annotations

import asyncio
import time

from common.config import get_kanana_mlx_model_path
from common.logging import get_logger

from ..errors import InferenceError, ModelLoadError
from ..postproc_schemas import PostprocRequest, PostprocResponse
from ..schemas import Correction
from . import _kanana2_diff as diff_atom
from . import _kanana2_prompt as prompt_atom
from . import _kanana2_runtime as rt

_LOG = get_logger(__name__)

# 커넥터 식별자 — registry 키와 동일. 파일명과 일관성 유지.
_NAME = "kanana2-mlx"

# 입력 대비 출력 생성 최대 토큰 배율.
# probe 평균 기준 입력 × 1.5 + 고정 버퍼 96 이면 안전한 상한이 된다.
_MAX_TOKENS_RATIO = 1.5
_MAX_TOKENS_FLOOR = 96
_MAX_TOKENS_CEIL = 4096


class Kanana2MlxConnector:
    """Kanana MLX 후처리 커넥터.

    클래스 레벨 싱글톤으로 모델을 1회만 로드한다 (ASR 패턴과 동일).
    인스턴스를 여러 번 생성해도 무방하지만 registry 를 통한 공유를 권장.
    """

    # Protocol 요구: name 속성
    name: str = _NAME

    # 로드 락은 인스턴스 간 공유 — 클래스 변수
    _load_lock: asyncio.Lock | None = None

    async def refine(self, req: PostprocRequest) -> PostprocResponse:
        """OCR 텍스트를 받아 교정 결과를 반환한다.

        PostprocRequest 를 단일 입력 규약으로 받아 PostprocResponse 를 반환한다.
        """
        corrections_pyd, refined, latency_ms, hallucination = await self._run_pipeline(req)
        return PostprocResponse(
            refined_text=refined,
            corrections=corrections_pyd,
            hallucination_suspect=hallucination,
            model=self.name,
            latency_ms=latency_ms,
            input_char_count=len(req.ocr_text),
            output_char_count=len(refined),
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그.

        - korean: 한국어 최적화 (Kakao Kanana 계열)
        - latex_preserve: 수식 블록 보존 파이프라인 구현
        - mlx: Apple Silicon MLX 런타임
        - hallucination_check: 응답 객체에 의심 플래그 동봉
        - diff: 교정 diff(corrections) 포함 반환
        """
        return feature in {
            "korean",
            "latex_preserve",
            "mlx",
            "hallucination_check",
            "diff",
        }

    # ─── 내부 파이프라인 ─────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        req: PostprocRequest,
    ) -> tuple[list[Correction], str, float, bool]:
        """공통 추론 파이프라인 — corrections(Pydantic), refined, latency, hallucination."""
        # 1) 프롬프트 구성 (수식 마스킹 포함)
        messages, masked = prompt_atom.build_chat_messages(
            ocr_text=req.ocr_text,
            preserve_latex=req.preserve_latex,
            language_hint=req.language_hint,
        )
        # 2) 모델 확보 + chat template 적용
        await self._ensure_loaded()
        _model, tok, _mid = rt.get_loaded()
        prompt_text = tok.apply_chat_template(messages, add_generation_prompt=True)
        # 3) 실제 추론 (블로킹 → 스레드)
        max_tokens = self._resolve_max_tokens(req)
        t0 = time.perf_counter()
        try:
            raw_output = await asyncio.to_thread(
                rt.run_generate, prompt_text, max_tokens,
            )
        except Exception as exc:
            _LOG.exception("kanana2-mlx 추론 실패")
            raise InferenceError(f"Kanana postproc inference failed: {exc}") from exc
        latency_ms = (time.perf_counter() - t0) * 1000.0
        # 4) 결과 정제 + LaTeX 복원 + diff
        trimmed = diff_atom.trim_model_output(raw_output)
        refined = masked.restore(trimmed) if masked is not None else trimmed
        corrections = diff_atom.diff_corrections(req.ocr_text, refined)
        hallucination = diff_atom.detect_hallucination(req.ocr_text, refined)
        return corrections, refined, latency_ms, hallucination

    # ─── 로드 관리 ───────────────────────────────────────────────────────

    @classmethod
    async def _ensure_loaded(cls) -> None:
        """싱글톤 로드를 한 번만 수행하도록 직렬화."""
        if rt.is_loaded():
            return
        if cls._load_lock is None:
            cls._load_lock = asyncio.Lock()
        async with cls._load_lock:
            if rt.is_loaded():
                return
            model_id = get_kanana_mlx_model_path()
            try:
                await asyncio.to_thread(rt.load, model_id)
            except ImportError as exc:
                raise ModelLoadError(
                    "mlx_lm 라이브러리가 설치되어 있지 않음. "
                    "`.venv-llm-postproc` 활성화 후 `uv pip install mlx-lm` 실행 필요",
                ) from exc
            except Exception as exc:
                raise ModelLoadError(
                    f"Kanana MLX 모델 로드 실패 (model_id={model_id}): {exc}",
                ) from exc

    @staticmethod
    def _resolve_max_tokens(req: PostprocRequest) -> int:
        """요청 max_tokens 를 입력 길이 기반 상/하한으로 보정."""
        if req.max_tokens is not None:
            return req.max_tokens
        estimated = int(len(req.ocr_text) * _MAX_TOKENS_RATIO) + _MAX_TOKENS_FLOOR
        return max(_MAX_TOKENS_FLOOR, min(estimated, _MAX_TOKENS_CEIL))

"""애플리케이션 공용 설정 모듈.

.env 값을 한 곳에서만 읽고, 다른 모듈은 여기 함수/상수만 참조한다.
이렇게 해야 테스트에서 monkeypatch 대상이 일원화되고,
커넥터 내부에 os.getenv()가 흩어지는 것을 막는다.
"""
from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 루트 — common/config.py 기준 부모의 부모
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 모델 캐시 기본 경로. 모델 다운로드 스크립트가 여기에 저장함
_DEFAULT_MODELS_DIR = _PROJECT_ROOT / "models_cache"


def get_asr_model_name() -> str:
    """레지스트리 키를 반환. 미지정 시 로컬 Mac 기본값."""
    # 기본값은 mlx-qwen3-asr — 로컬 개발 환경 가정
    return os.getenv("AI_MODEL_ASR", "mlx-qwen3-asr")


def get_models_cache_dir() -> Path:
    """모델 가중치 로컬 캐시 디렉터리 경로."""
    # 없으면 생성해서 반환 — 다운로드 스크립트와 동일한 동작
    _DEFAULT_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_MODELS_DIR


def get_denoise_model_name() -> str:
    """Denoise 커넥터 레지스트리 키. 미지정 시 로컬 Mac 기본값."""
    # 기본값은 mossformer2-se-48k — clearvoice + PyTorch MPS 로컬 실행
    return os.getenv("AI_MODEL_DENOISE", "mossformer2-se-48k")


def get_mossformer2_se_checkpoint_dir() -> str:
    """MossFormer2_SE_48K 체크포인트 디렉터리 (clearvoice가 읽는 경로).

    clearvoice 라이브러리는 args.checkpoint_dir를 CWD 기준 "checkpoints/<Model>"
    기본값으로 사용한다. .env에 override 있으면 그걸 사용.
    """
    # 사용자 지정 경로 우선
    local = os.getenv("MOSSFORMER2_SE_MODEL_PATH", "").strip()
    if local:
        return str(Path(local).expanduser().resolve())
    # 기본값: 샌드박스 루트의 checkpoints/MossFormer2_SE_48K
    return str(_PROJECT_ROOT / "checkpoints" / "MossFormer2_SE_48K")


def get_mossformer2_sr_checkpoint_dir() -> str:
    """MossFormer2_SR_48K 체크포인트 디렉터리 (선택적 슈퍼해상도)."""
    local = os.getenv("MOSSFORMER2_SR_MODEL_PATH", "").strip()
    if local:
        return str(Path(local).expanduser().resolve())
    return str(_PROJECT_ROOT / "checkpoints" / "MossFormer2_SR_48K")


def get_tts_model_name() -> str:
    """TTS 커넥터 레지스트리 키. 미지정 시 로컬 Mac 기본값."""
    # 기본값은 mlx-audio-qwen3-tts — Blaizzy/mlx-audio + Qwen3-TTS 12Hz bf16
    return os.getenv("AI_MODEL_TTS", "mlx-audio-qwen3-tts")


def get_qwen3_tts_model_path() -> str:
    """Qwen3-TTS(MLX 커뮤니티 bf16) 가중치 경로.

    .env 에 QWEN3_TTS_MODEL_PATH 있으면 우선 사용.
    없으면 HF 허브 repo id 를 반환해 mlx_audio.tts.utils.load 가 캐시 자동 처리.
    mlx-community 레포는 speech_tokenizer/ 서브디렉터리와 text tokenizer 파일을
    모두 포함하므로 별도 토크나이저 다운로드는 필요 없다.
    """
    # 사용자 지정 로컬 경로 우선 — 절대경로로 치환
    local = os.getenv("QWEN3_TTS_MODEL_PATH", "").strip()
    if local:
        return str(Path(local).expanduser().resolve())
    # 기본값: HF 허브 repo id — mlx_audio.tts.utils.load 가 내부에서 get_model_path 호출
    return "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"


def get_postproc_model_name() -> str:
    """OCR 후처리 LLM 커넥터 레지스트리 키. 미지정 시 로컬 Mac 기본값."""
    # 기본값: kanana2-mlx — Kanana-1.5-2.1B MLX 4bit 로컬 실행
    # 이름은 kanana2-* 로 통일해 향후 Kanana 2.x 출시 시 같은 슬롯으로 업그레이드
    return os.getenv("AI_MODEL_POSTPROC", "kanana2-mlx")


def get_rate_limit_rpm() -> int:
    """분당 최대 요청 수. 미지정 시 60."""
    # 내부 AI 서비스이므로 기본값을 넉넉히 설정 — GPU 집약 엔드포인트 보호가 목적
    return int(os.getenv("RATE_LIMIT_RPM", "60"))


def get_rate_limit_burst() -> int:
    """순간 허용 버스트 요청 수. 미지정 시 10."""
    # 버스트는 순간적인 스파이크를 허용하되 지속적 과부하를 차단
    return int(os.getenv("RATE_LIMIT_BURST", "10"))



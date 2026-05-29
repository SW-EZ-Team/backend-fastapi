"""TTS V2 API 요청/응답 Pydantic 모델 정의.

요청 모델은 FastAPI 엔드포인트에서 바로 사용되며,
응답 모델은 파이프라인 실행 결과를 클라이언트에 직렬화하는 데 쓰인다.
이 파일은 pydantic 이외의 내부 모듈을 import 하지 않는다 (SRP).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TTSV2TextRequest(BaseModel):
    """텍스트 직접 입력 TTS V2 요청 모델.

    voice_profile_id 가 있으면 서버에 등록된 고정 튜터 음성을 사용한다.
    ref_audio_base64 이 None 이면 서버의 기본 고정 튜터 프로필을 사용한다.
    skip_planner=True 이면 LLM 낭독 계획 단계를 건너뛰고 normalized_text를 그대로 사용한다.
    qc_engine 은 합성 후 품질 검증에 사용할 엔진을 선택한다.
    """

    text: str = Field(..., min_length=1, max_length=50000)
    # 서버에 등록된 고정 튜터 음성 프로필 ID. 예: tutor_1, tutor_2
    voice_profile_id: str | None = Field(default=None, max_length=80)
    # 레퍼런스 음성 — base64 인코딩된 오디오 바이너리. None 이면 기본값 사용
    ref_audio_base64: str | None = None
    # 레퍼런스 음성의 전사 텍스트 — 음성 클로닝 품질에 직결된다. None 이면 기본값 사용
    ref_text: str | None = Field(default=None, max_length=500)
    language: str = Field(default="ko")
    # 재생 속도 배율 — 0.5(절반 속도) ~ 2.0(2배속)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    # True 이면 LLM 낭독 계획 노드를 건너뛴다 (빠른 합성 우선 시)
    skip_planner: bool = Field(default=False)
    # True 이면 loudness 정규화·크로스페이드 등 후처리를 건너뛴다
    skip_postfx: bool = Field(default=False)
    # "whisperx" / "v1_asr" / "both" — QC에 사용할 ASR 엔진 선택
    qc_engine: str = Field(default="whisperx")

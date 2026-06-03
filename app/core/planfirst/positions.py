"""정답 위치 균등배치 단일 소스.

ChapterStudio_V1.postprocess.quiz_balance.balanced_target_positions 와
ExamForge_V1.pipeline.nodes.concept_blueprint._balanced_target_positions 가
동일 알고리즘을 중복 구현하고 있었다. 이 모듈이 두 구현의 단일 소스다.

호출처 위임 현황:
  - ChapterStudio quiz_balance.balanced_target_positions  → 이 모듈에 위임
  - ExamForge concept_blueprint._balanced_target_positions → 이 모듈에 위임

byte-identical 증명: tests/planfirst/test_positions.py 참조.
"""
from __future__ import annotations

import hashlib
import random


def balanced_target_positions(
    count: int,
    num_choices: int = 4,
    seed: int = 0,
) -> list[int]:
    """count개 슬롯에 목표 정답 위치를 균등하게 만들고 결정적으로 섞는다.

    0번부터 num_choices-1번까지를 순환 배정(0,1,2,3,0,1,2,3,...)한 뒤
    고정 seed로 섞어 결정적이고 재현 가능한 배분을 보장한다.

    경계값 계약(원본 byte-identical 보존):
      - count <= 0 : 빈 목록 [] 반환. ExamForge 원본의 관용 동작과 동일하며,
        num_choices 값에 관계없이 조기 반환한다(원본도 early return).
      - count > 0, num_choices < 1 : ValueError. 원본은 이 경로에서 num_choices=0일 때
        ZeroDivisionError를 던졌으나(modulo by zero), 정상 입력이 아님을 명시하는
        ValueError로 계약을 분명히 한다. 둘 다 "정상값을 반환하지 않는다"는 점에서 일치한다.

    Args:
        count: 슬롯(문항/퀴즈) 수. 0 이하면 빈 목록을 반환한다.
        num_choices: 보기(선택지) 수. count>0일 때 1 이상이어야 한다.
        seed: random.Random 고정 시드.

    Returns:
        길이 count인 0-index 위치 목록(count<=0이면 빈 목록).

    Raises:
        ValueError: count > 0 인데 num_choices < 1 인 경우.
    """
    if count <= 0:
        # 원본 관용 동작: 비양수 count는 num_choices와 무관하게 [] 조기 반환.
        return []
    if num_choices < 1:
        raise ValueError("num_choices는 1 이상이어야 한다.")
    positions = [idx % num_choices for idx in range(count)]
    random.Random(seed).shuffle(positions)
    return positions


def seed_from_key(seed_key: str) -> int:
    """파이썬 해시 랜덤화에 영향받지 않는 고정 seed를 만든다.

    빈 문자열이면 0을 반환한다. 그 외에는 SHA-256 앞 8바이트를 big-endian 정수로 변환한다.
    ChapterStudio·ExamForge 양쪽의 _seed_from_key와 byte-identical이다.
    """
    if not seed_key:
        return 0
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


__all__ = ["balanced_target_positions", "seed_from_key"]

"""슬라이드 채팅 컨텍스트 빌더 — 운영 DB 데이터 기반 컨텍스트 구성.

데모 파이프라인 제거 후 이 모듈은 빈 공개 인터페이스를 유지한다.
운영 버전은 lesson_id로 DB에서 GenerationContext를 로드한 뒤
SlideChatContext를 직접 조립한다.
"""
from __future__ import annotations

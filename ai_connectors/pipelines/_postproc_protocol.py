"""후처리 커넥터 Protocol 재수출 모듈.

이전에는 이 파일에 PostprocConnector 를 별도로 선언했으나
base.py 에 공식 PostprocConnector Protocol 이 추가됨에 따라
이중 선언을 제거하고 base.py 를 단일 정의 소스로 통일한다.

기존 import 경로(from ai_connectors.pipelines._postproc_protocol import PostprocConnector)
가 깨지지 않도록 re-export alias 만 남긴다.
"""
from ai_connectors.base import PostprocConnector

__all__ = ["PostprocConnector"]

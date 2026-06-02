"""boto3 기반 S3 클라이언트 생성."""
from __future__ import annotations

import importlib
from typing import Protocol

from .config import ObjectStorageConfigError, S3Settings, load_s3_settings


class S3ClientProtocol(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object:
        """S3 호환 put_object 호출 형태를 고정한다."""


def create_s3_client(settings: S3Settings | None = None) -> S3ClientProtocol:
    """endpoint_url이 있으면 MinIO, 없으면 AWS 기본 엔드포인트를 사용한다."""
    resolved = load_s3_settings() if settings is None else settings
    try:
        boto3 = importlib.import_module("boto3")
    except ModuleNotFoundError as exc:
        raise ObjectStorageConfigError("boto3 패키지가 설치되지 않았다.") from exc

    params: dict[str, str] = {"region_name": resolved.region}
    if resolved.endpoint_url is not None:
        params["endpoint_url"] = resolved.endpoint_url
    if resolved.access_key is not None:
        params["aws_access_key_id"] = resolved.access_key
    if resolved.secret_key is not None:
        params["aws_secret_access_key"] = resolved.secret_key
    return boto3.client("s3", **params)


__all__ = ["S3ClientProtocol", "create_s3_client"]

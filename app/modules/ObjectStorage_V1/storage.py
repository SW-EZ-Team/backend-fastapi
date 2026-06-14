"""S3 호환 객체 업로드와 공개 URL 생성."""
from __future__ import annotations

import asyncio
from urllib.parse import quote

from .client import create_s3_client
from .config import ObjectStorageConfigError, S3Settings, load_s3_settings


class ObjectStorageUploadError(RuntimeError):
    """객체 업로드 실패를 호출부가 명확히 구분하도록 감싼다."""


async def put_object(data: bytes, key: str, content_type: str) -> str:
    """객체를 업로드하고 브라우저가 접근할 공개 URL을 반환한다."""
    settings = load_s3_settings()
    _validate_upload_input(data, key, content_type, settings)
    return await asyncio.to_thread(_put_object_sync, data, key, content_type, settings)


def build_public_url(settings: S3Settings, key: str) -> str:
    """외부 브라우저 기준 공개 URL을 설정 우선순위대로 만든다."""
    encoded_key = quote(key.lstrip("/"), safe="/")
    if settings.public_url_base is not None:
        return f"{settings.public_url_base.rstrip('/')}/{encoded_key}"
    if settings.endpoint_url is not None:
        return f"{settings.endpoint_url.rstrip('/')}/{settings.bucket}/{encoded_key}"
    return f"https://{settings.bucket}.s3.{settings.region}.amazonaws.com/{encoded_key}"


def to_internal_url(url: str) -> str:
    """브라우저용 공개 URL을 컨테이너 내부에서 접근 가능한 endpoint URL로 변환한다.

    로컬 스택에서 공개 URL 베이스(예: http://localhost:9000/sw-ez-media)는 호스트 브라우저
    기준이라 컨테이너 안에서는 닿지 않는다. 설정된 public_url_base 로 시작하는 URL이면
    endpoint_url(예: http://minio:9000) + 버킷 경로로 바꿔 내부 다운로드가 가능하게 한다.
    조건이 안 맞으면(설정 없음, 외부 URL 등) 원본을 그대로 반환한다.
    """
    settings = load_s3_settings()
    if settings.public_url_base is None or settings.endpoint_url is None:
        return url
    base = settings.public_url_base.rstrip("/")
    if not url.startswith(base + "/"):
        return url
    key_part = url[len(base) + 1 :]
    return f"{settings.endpoint_url.rstrip('/')}/{settings.bucket}/{key_part}"


def _put_object_sync(data: bytes, key: str, content_type: str, settings: S3Settings) -> str:
    client = create_s3_client(settings)
    try:
        client.put_object(Bucket=settings.bucket, Key=key, Body=data, ContentType=content_type)
    except Exception as exc:
        raise ObjectStorageUploadError(f"S3 객체 업로드 실패: bucket={settings.bucket}, key={key}") from exc
    return build_public_url(settings, key)


def _validate_upload_input(data: bytes, key: str, content_type: str, settings: S3Settings) -> None:
    if not settings.enabled:
        raise ObjectStorageConfigError("S3_ENABLED가 true가 아니다.")
    if data == b"":
        raise ObjectStorageConfigError("업로드할 data가 비어 있다.")
    if key == "" or key.startswith("/"):
        raise ObjectStorageConfigError("key는 빈 값이 아니고 슬래시로 시작하면 안 된다.")
    if content_type == "":
        raise ObjectStorageConfigError("content_type이 비어 있다.")


__all__ = ["ObjectStorageUploadError", "build_public_url", "put_object", "to_internal_url"]

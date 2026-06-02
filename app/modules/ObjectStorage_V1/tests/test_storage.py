from __future__ import annotations

import pytest

from app.modules.ObjectStorage_V1 import ObjectStorageConfigError, put_object, s3_enabled
from app.modules.ObjectStorage_V1.config import S3Settings
from app.modules.ObjectStorage_V1 import storage


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object:
        self.calls.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {"ETag": "fake"}


@pytest.mark.asyncio
async def test_put_object_uploads_and_returns_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client()
    monkeypatch.setenv("S3_ENABLED", "true")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    monkeypatch.setenv("S3_BUCKET", "sw-ez-media")
    monkeypatch.setenv("S3_PUBLIC_URL_BASE", "http://localhost:9000/sw-ez-media")
    monkeypatch.setattr(storage, "create_s3_client", lambda settings: client)

    url = await put_object(b"RIFFfakeWAVE", "tts/a.wav", "audio/wav")

    assert url == "http://localhost:9000/sw-ez-media/tts/a.wav"
    assert client.calls == [
        {"Bucket": "sw-ez-media", "Key": "tts/a.wav", "Body": b"RIFFfakeWAVE", "ContentType": "audio/wav"}
    ]


@pytest.mark.asyncio
async def test_put_object_requires_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENABLED", "false")

    with pytest.raises(ObjectStorageConfigError, match="S3_ENABLED"):
        await put_object(b"data", "tts/a.wav", "audio/wav")


def test_s3_enabled_reads_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENABLED", "true")

    assert s3_enabled() is True


def test_build_public_url_uses_endpoint_when_public_base_missing() -> None:
    settings = S3Settings(
        enabled=True,
        endpoint_url="http://minio:9000",
        region="us-east-1",
        bucket="sw-ez-media",
        access_key="minioadmin",
        secret_key="minioadmin",
        public_url_base=None,
    )

    assert storage.build_public_url(settings, "tts/공백 파일.wav") == (
        "http://minio:9000/sw-ez-media/tts/%EA%B3%B5%EB%B0%B1%20%ED%8C%8C%EC%9D%BC.wav"
    )


def test_build_public_url_uses_aws_url_when_endpoint_missing() -> None:
    settings = S3Settings(
        enabled=True,
        endpoint_url=None,
        region="ap-northeast-2",
        bucket="prod-media",
        access_key=None,
        secret_key=None,
        public_url_base=None,
    )

    assert storage.build_public_url(settings, "tts/a.wav") == "https://prod-media.s3.ap-northeast-2.amazonaws.com/tts/a.wav"

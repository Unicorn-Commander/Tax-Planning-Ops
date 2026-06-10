from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class StoredBlob:
    key: str
    encrypted: bool


async def put_object(
    *,
    key: str,
    data: bytes,
    content_type: str,
    settings: Settings,
) -> StoredBlob:
    if not settings.GARAGE_ACCESS_KEY or not settings.GARAGE_SECRET_KEY:
        return StoredBlob(key=key, encrypted=False)
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.GARAGE_ENDPOINT,
        aws_access_key_id=settings.GARAGE_ACCESS_KEY,
        aws_secret_access_key=settings.GARAGE_SECRET_KEY,
        region_name="us-east-1",
    )
    client.put_object(
        Bucket=settings.GARAGE_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )
    return StoredBlob(key=key, encrypted=True)

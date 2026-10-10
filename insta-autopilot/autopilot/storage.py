from __future__ import annotations

import boto3

from .config import env


def _client():
    return boto3.client(
        "s3",
        endpoint_url=env("S3_ENDPOINT_URL"),
        aws_access_key_id=env("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=env("S3_SECRET_ACCESS_KEY"),
        region_name=env("S3_REGION", required=False, default="auto"),
    )


def upload_public(path, key: str) -> str:
    """Upload a video and return the public URL Instagram will fetch it from."""
    _client().upload_file(str(path), env("S3_BUCKET"), key,
                          ExtraArgs={"ContentType": "video/mp4"})
    return f"{env('S3_PUBLIC_BASE_URL').rstrip('/')}/{key}"


def delete(key: str) -> None:
    _client().delete_object(Bucket=env("S3_BUCKET"), Key=key)

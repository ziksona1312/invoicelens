"""Object storage through the S3 API (SeaweedFS locally, any S3-compatible store elsewhere)."""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from app.service.config import get_settings


@lru_cache
def get_client():
    s = get_settings()
    # Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment.
    return boto3.client("s3", endpoint_url=s.s3_endpoint_url, region_name=s.s3_region)


def ensure_bucket() -> None:
    client, bucket = get_client(), get_settings().s3_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def put(key: str, data: bytes) -> None:
    get_client().put_object(
        Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType="application/pdf"
    )


def get(key: str) -> bytes:
    return get_client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()

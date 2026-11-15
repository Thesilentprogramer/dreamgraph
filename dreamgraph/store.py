"""S3-compatible JSON store.

Local runs use in-process moto. Production passes ``DG_S3_ENDPOINT`` (or
``AWS_ENDPOINT_URL``) pointing at a Railway bucket. Local disk is not a
backend; ``export_json`` is an explicit copy for the dashboard and git.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from dreamgraph.config import S3_ACCESS_KEY, S3_BUCKET, S3_ENDPOINT, S3_REGION, S3_SECRET_KEY


class ObjectStore:
    def __init__(
        self,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        *,
        use_moto: bool | None = None,
    ):
        self.bucket = bucket or S3_BUCKET
        self.endpoint_url = endpoint_url if endpoint_url is not None else S3_ENDPOINT
        self._mock = None
        if use_moto is None:
            use_moto = not self.endpoint_url
        if use_moto:
            from moto import mock_aws

            self._mock = mock_aws()
            self._mock.start()
            self.client = boto3.client(
                "s3",
                region_name=S3_REGION,
                aws_access_key_id="testing",
                aws_secret_access_key="testing",
            )
            self.client.create_bucket(Bucket=self.bucket)
            self.backend = "moto"
        else:
            self.client = boto3.client(
                "s3",
                region_name=S3_REGION,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            self._ensure_bucket()
            self.backend = "s3"

    def close(self) -> None:
        if self._mock is not None:
            self._mock.stop()
            self._mock = None

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_json(self, key: str, document: Any) -> str:
        raw = json.dumps(document, indent=2, sort_keys=True).encode()
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=raw,
            ContentType="application/json",
        )
        return key

    def get_json(self, key: str) -> Any:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(response["Body"].read().decode())

    def export_json(self, key: str, path: Path) -> Path:
        """Copy one object out for the dashboard. The bucket remains the write path."""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.get_json(key), indent=2, sort_keys=True) + "\n")
        return path

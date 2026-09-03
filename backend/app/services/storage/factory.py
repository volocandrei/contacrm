"""Singurul loc care știe ce provider de stocare este activ (ADR-004).

Restul aplicației cere `StorageProvider` și primește ceva care respectă
protocolul. Nimic din logica de business nu întreabă vreodată „ești disc sau
ești S3?" — dacă ar întreba, alegerea nu ar mai fi reversibilă.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from app.core.config import Settings, settings
from app.services.storage.base import StorageProvider
from app.services.storage.local import LocalStorageProvider
from app.services.storage.s3 import S3StorageProvider

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


def build_s3_client(config: Settings) -> S3Client:
    """Clientul S3, construit din configurare.

    `endpoint_url` gol înseamnă AWS. Pentru Supabase Storage, Cloudflare R2 sau un
    MinIO local se pune adresa lor și restul rămâne identic.

    `s3v4` este cerut explicit: unele implementări compatibile nu acceptă semnături
    mai vechi, iar negocierea tăcută ar eșua abia la prima scriere reală.
    """
    return boto3.client(
        "s3",
        endpoint_url=config.s3_endpoint_url or None,
        region_name=config.s3_region,
        aws_access_key_id=config.s3_access_key_id or None,
        aws_secret_access_key=config.s3_secret_access_key or None,
        config=Config(
            signature_version="s3v4",
            # Cheile noastre conțin `/`, deci stilul „path" evită dependența de DNS
            # per-bucket, pe care serviciile compatibile S3 nu o oferă întotdeauna.
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def build_storage_provider(config: Settings | None = None) -> StorageProvider:
    """Providerul cerut de `STORAGE_PROVIDER`.

    `Settings` a validat deja numele, deci aici nu există ramură de „necunoscut":
    o valoare greșită oprește pornirea aplicației, nu ajunge până la primul upload.
    """
    config = config or settings
    if config.storage_provider == "s3":
        return S3StorageProvider(build_s3_client(config), config.s3_bucket, prefix=config.s3_prefix)
    return LocalStorageProvider(config.storage_path)


@lru_cache(maxsize=1)
def get_storage_provider() -> StorageProvider:
    """Un singur provider pentru tot procesul.

    Clientul S3 ține un pool de conexiuni HTTP; construit la fiecare cerere, ar
    plăti un handshake TLS de fiecare dată.
    """
    return build_storage_provider()


__all__ = ["build_s3_client", "build_storage_provider", "get_storage_provider"]

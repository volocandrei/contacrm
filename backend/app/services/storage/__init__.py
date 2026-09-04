"""Stocarea documentelor (ADR-004)."""

from app.services.storage.base import (
    ObjectNotFoundError,
    Readable,
    StorageError,
    StorageProvider,
    StoredObject,
)
from app.services.storage.factory import (
    build_s3_client,
    build_storage_provider,
    get_storage_provider,
)
from app.services.storage.keys import (
    EFACTURA_FILES,
    InvalidStorageKeyError,
    archive_key,
    efactura_key,
    extension_for,
    original_key,
    validate_key,
)
from app.services.storage.local import LocalStorageProvider
from app.services.storage.s3 import S3StorageProvider

__all__ = [
    "EFACTURA_FILES",
    "InvalidStorageKeyError",
    "LocalStorageProvider",
    "ObjectNotFoundError",
    "Readable",
    "S3StorageProvider",
    "StorageError",
    "StorageProvider",
    "StoredObject",
    "archive_key",
    "build_s3_client",
    "build_storage_provider",
    "efactura_key",
    "extension_for",
    "get_storage_provider",
    "original_key",
    "validate_key",
]

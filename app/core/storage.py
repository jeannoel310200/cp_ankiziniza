"""Stockage d'objets (photos de profil, pièces d'identité).

Deux moteurs :
- ``local`` : écrit dans ``uploads/`` — uniquement pour les tests et le
  développement local. Jamais activé en production.
- ``s3``    : RustFS (API compatible S3) via aioboto3. Aucune écriture de
  fichier locale. Le versionnement est géré côté bucket (RustFS) : l'appli ne
  supprime jamais d'objet, elle publie uniquement de nouvelles versions.
"""

from pathlib import Path

from app.core.config import get_settings

_UPLOAD_ROOT = Path("uploads")


def _strip_root(key: str) -> str:
    """Les clés de stockage commencent déjà par `uploads/`."""
    return key[len("uploads/") :] if key.startswith("uploads/") else key


class StorageDriver:
    async def save_bytes(self, key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError

    async def read_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError


class LocalStorageDriver(StorageDriver):
    """Repli développement/tests : conserve l'ancien layout ``uploads/...``."""

    async def save_bytes(self, key: str, content: bytes, content_type: str) -> None:
        target = _UPLOAD_ROOT / _strip_root(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def read_bytes(self, key: str) -> bytes:
        target = _UPLOAD_ROOT / _strip_root(key)
        if not target.is_file():
            raise FileNotFoundError(key)
        return target.read_bytes()

    async def exists(self, key: str) -> bool:
        return (_UPLOAD_ROOT / _strip_root(key)).is_file()


class S3StorageDriver(StorageDriver):
    """RustFS S3 : upload uniquement, aucune suppression locale ou distante."""

    def __init__(self) -> None:
        settings = get_settings()
        if not all(
            (
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket,
            )
        ):
            raise RuntimeError(
                "STORAGE_DRIVER=s3 requires S3_ENDPOINT_URL, S3_ACCESS_KEY, "
                "S3_SECRET_KEY and S3_BUCKET"
            )
        self._endpoint_url = settings.s3_endpoint_url
        self._access_key = settings.s3_access_key
        self._secret_key = settings.s3_secret_key
        self._bucket = settings.s3_bucket
        self._region = settings.s3_region
        self._use_path_style = settings.s3_use_path_style

    def _config(self):
        from aiobotocore.config import AioConfig

        return AioConfig(
            s3={
                "addressing_style": "path" if self._use_path_style else "virtual",
                "signature_version": "s3v4",
            }
        )

    async def save_bytes(self, key: str, content: bytes, content_type: str) -> None:
        import aioboto3

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=self._config(),
        ) as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )

    async def read_bytes(self, key: str) -> bytes:
        import aioboto3

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=self._config(),
        ) as client:
            response = await client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            try:
                return await body.read()
            finally:
                body.close()

    async def exists(self, key: str) -> bool:
        import aioboto3

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=self._config(),
        ) as client:
            try:
                await client.head_object(Bucket=self._bucket, Key=key)
                return True
            except Exception:
                return False


def get_storage() -> StorageDriver:
    settings = get_settings()
    if settings.storage_driver == "s3":
        return S3StorageDriver()
    return LocalStorageDriver()


def is_s3_storage() -> bool:
    return get_settings().storage_driver == "s3"

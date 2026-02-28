"""
Storage backends for filing PDFs to various destinations.

Provides a StorageBackend abstract base class and implementations
for local filesystem, Nextcloud WebDAV, Google Drive, and Dropbox.
"""

from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger("skpdf.storage")


class StorageBackend(ABC):
    """Abstract base class for PDF filing storage backends.

    All backends must implement store() and ensure_directory().
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier (e.g., 'local', 'nextcloud')."""

    @abstractmethod
    def store(
        self,
        source_path: Path,
        dest_path: str,
        metadata_yaml: Optional[str] = None,
    ) -> str:
        """Store a file to this backend.

        Args:
            source_path: Local path to the file to store.
            dest_path: Destination path relative to the backend root.
            metadata_yaml: Optional YAML metadata to store alongside.

        Returns:
            str: The full destination path/URI of the stored file.

        Raises:
            StorageError: If the file could not be stored.
        """

    @abstractmethod
    def ensure_directory(self, path: str) -> None:
        """Ensure a directory exists at the given path.

        Args:
            path: Directory path relative to the backend root.
        """

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a file exists at the given path.

        Args:
            path: Path relative to the backend root.
        """

    def store_metadata(self, metadata_yaml: str, dest_path: str) -> str:
        """Store a metadata sidecar file.

        Default implementation appends .meta.yml to the dest_path.

        Args:
            metadata_yaml: YAML content to write.
            dest_path: Path of the PDF file (metadata path is derived).

        Returns:
            str: Path to the stored metadata file.
        """
        meta_path = dest_path.rsplit(".", 1)[0] + ".meta.yml"
        return self._write_metadata(metadata_yaml, meta_path)

    def _write_metadata(self, content: str, path: str) -> str:
        """Write metadata content — override in subclasses."""
        raise NotImplementedError


class StorageError(Exception):
    """Raised when a storage operation fails."""


class LocalBackend(StorageBackend):
    """Store files to local filesystem.

    Args:
        root: Root directory for filing (default: ~/Documents).
    """

    def __init__(self, root: Optional[Path] = None):
        self._root = root or Path.home() / "Documents"

    @property
    def name(self) -> str:
        return "local"

    @property
    def root(self) -> Path:
        return self._root

    def store(
        self,
        source_path: Path,
        dest_path: str,
        metadata_yaml: Optional[str] = None,
    ) -> str:
        full_dest = self._root / dest_path
        self.ensure_directory(str(full_dest.parent.relative_to(self._root)))

        shutil.copy2(source_path, full_dest)
        logger.info("Filed %s -> %s", source_path.name, full_dest)

        if metadata_yaml:
            self.store_metadata(metadata_yaml, dest_path)

        return str(full_dest)

    def ensure_directory(self, path: str) -> None:
        full_path = self._root / path
        full_path.mkdir(parents=True, exist_ok=True)

    def exists(self, path: str) -> bool:
        return (self._root / path).exists()

    def _write_metadata(self, content: str, path: str) -> str:
        full_path = self._root / path
        full_path.write_text(content, encoding="utf-8")
        return str(full_path)


class NextcloudWebDAVBackend(StorageBackend):
    """Store files to Nextcloud via WebDAV.

    Args:
        base_url: Nextcloud WebDAV URL (e.g., https://cloud.example.com/remote.php/dav/files/user/).
        username: Nextcloud username.
        password: Nextcloud password or app token.
    """

    def __init__(self, base_url: str, username: str, password: str):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password

    @property
    def name(self) -> str:
        return "nextcloud"

    def store(
        self,
        source_path: Path,
        dest_path: str,
        metadata_yaml: Optional[str] = None,
    ) -> str:
        import requests

        url = f"{self._base_url}/{dest_path}"
        self.ensure_directory("/".join(dest_path.split("/")[:-1]))

        with open(source_path, "rb") as f:
            resp = requests.put(
                url,
                data=f,
                auth=(self._username, self._password),
                timeout=60,
            )

        if resp.status_code not in (200, 201, 204):
            raise StorageError(
                f"Nextcloud upload failed ({resp.status_code}): {resp.text[:200]}"
            )

        logger.info("Filed %s -> nextcloud:%s", source_path.name, dest_path)

        if metadata_yaml:
            self.store_metadata(metadata_yaml, dest_path)

        return f"nextcloud:{dest_path}"

    def ensure_directory(self, path: str) -> None:
        import requests

        parts = path.strip("/").split("/")
        current = ""
        for part in parts:
            if not part:
                continue
            current = f"{current}/{part}" if current else part
            url = f"{self._base_url}/{current}/"
            requests.request(
                "MKCOL",
                url,
                auth=(self._username, self._password),
                timeout=30,
            )

    def exists(self, path: str) -> bool:
        import requests

        url = f"{self._base_url}/{path}"
        resp = requests.head(
            url,
            auth=(self._username, self._password),
            timeout=15,
        )
        return resp.status_code == 200

    def _write_metadata(self, content: str, path: str) -> str:
        import requests

        url = f"{self._base_url}/{path}"
        resp = requests.put(
            url,
            data=content.encode("utf-8"),
            auth=(self._username, self._password),
            headers={"Content-Type": "text/yaml"},
            timeout=30,
        )
        if resp.status_code not in (200, 201, 204):
            logger.warning("Failed to store metadata at %s", path)
        return f"nextcloud:{path}"


class GoogleDriveBackend(StorageBackend):
    """Store files to Google Drive.

    Args:
        credentials_path: Path to Google service account or OAuth credentials JSON.
        root_folder_id: Google Drive folder ID for the filing root.
    """

    def __init__(self, credentials_path: str, root_folder_id: str = "root"):
        self._credentials_path = credentials_path
        self._root_folder_id = root_folder_id
        self._service = None

    @property
    def name(self) -> str:
        return "gdrive"

    def _get_service(self):
        if self._service is not None:
            return self._service

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            self._credentials_path,
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def store(
        self,
        source_path: Path,
        dest_path: str,
        metadata_yaml: Optional[str] = None,
    ) -> str:
        from googleapiclient.http import MediaFileUpload

        service = self._get_service()
        folder_id = self._ensure_folder_chain(dest_path)

        media = MediaFileUpload(str(source_path), mimetype="application/pdf")
        file_metadata = {
            "name": source_path.name,
            "parents": [folder_id],
        }

        result = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()

        file_id = result["id"]
        logger.info("Filed %s -> gdrive:%s", source_path.name, file_id)

        if metadata_yaml:
            self._store_metadata_gdrive(metadata_yaml, source_path.stem, folder_id)

        return f"gdrive:{file_id}"

    def _ensure_folder_chain(self, path: str) -> str:
        """Create nested folders and return the leaf folder ID."""
        service = self._get_service()
        parts = Path(path).parent.parts
        parent_id = self._root_folder_id

        for folder_name in parts:
            query = (
                f"name='{folder_name}' and '{parent_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
            )
            results = service.files().list(q=query, fields="files(id)").execute()
            files = results.get("files", [])

            if files:
                parent_id = files[0]["id"]
            else:
                meta = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                }
                folder = service.files().create(body=meta, fields="id").execute()
                parent_id = folder["id"]

        return parent_id

    def _store_metadata_gdrive(self, content: str, stem: str, folder_id: str) -> None:
        from googleapiclient.http import MediaInMemoryUpload

        service = self._get_service()
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/yaml")
        meta = {
            "name": f"{stem}.meta.yml",
            "parents": [folder_id],
        }
        service.files().create(body=meta, media_body=media).execute()

    def ensure_directory(self, path: str) -> None:
        self._ensure_folder_chain(path + "/placeholder")

    def exists(self, path: str) -> bool:
        # Drive doesn't map well to paths; return False
        return False

    def _write_metadata(self, content: str, path: str) -> str:
        return f"gdrive:metadata"


class DropboxBackend(StorageBackend):
    """Store files to Dropbox.

    Args:
        access_token: Dropbox OAuth2 access token.
        root_path: Root path within Dropbox (default: /Documents).
    """

    def __init__(self, access_token: str, root_path: str = "/Documents"):
        self._access_token = access_token
        self._root_path = root_path.rstrip("/")

    @property
    def name(self) -> str:
        return "dropbox"

    def store(
        self,
        source_path: Path,
        dest_path: str,
        metadata_yaml: Optional[str] = None,
    ) -> str:
        import dropbox

        dbx = dropbox.Dropbox(self._access_token)
        full_path = f"{self._root_path}/{dest_path}"

        with open(source_path, "rb") as f:
            dbx.files_upload(
                f.read(),
                full_path,
                mode=dropbox.files.WriteMode.overwrite,
            )

        logger.info("Filed %s -> dropbox:%s", source_path.name, full_path)

        if metadata_yaml:
            meta_path = full_path.rsplit(".", 1)[0] + ".meta.yml"
            dbx.files_upload(
                metadata_yaml.encode("utf-8"),
                meta_path,
                mode=dropbox.files.WriteMode.overwrite,
            )

        return f"dropbox:{full_path}"

    def ensure_directory(self, path: str) -> None:
        import dropbox as dbx_module

        dbx = dbx_module.Dropbox(self._access_token)
        full_path = f"{self._root_path}/{path}"
        try:
            dbx.files_create_folder_v2(full_path)
        except Exception:
            pass  # Folder may already exist

    def exists(self, path: str) -> bool:
        import dropbox as dbx_module

        dbx = dbx_module.Dropbox(self._access_token)
        try:
            dbx.files_get_metadata(f"{self._root_path}/{path}")
            return True
        except Exception:
            return False

    def _write_metadata(self, content: str, path: str) -> str:
        import dropbox as dbx_module

        dbx = dbx_module.Dropbox(self._access_token)
        full_path = f"{self._root_path}/{path}"
        dbx.files_upload(
            content.encode("utf-8"),
            full_path,
            mode=dbx_module.files.WriteMode.overwrite,
        )
        return f"dropbox:{full_path}"


def get_backend(name: str, **kwargs) -> StorageBackend:
    """Factory to get a storage backend by name.

    Args:
        name: Backend name ('local', 'nextcloud', 'gdrive', 'dropbox').
        **kwargs: Backend-specific configuration.

    Returns:
        StorageBackend: Configured backend instance.

    Raises:
        ValueError: If the backend name is unknown.
    """
    backends = {
        "local": LocalBackend,
        "nextcloud": NextcloudWebDAVBackend,
        "gdrive": GoogleDriveBackend,
        "dropbox": DropboxBackend,
    }

    cls = backends.get(name)
    if cls is None:
        valid = ", ".join(sorted(backends.keys()))
        raise ValueError(f"Unknown storage backend '{name}'. Valid: {valid}")

    return cls(**kwargs)

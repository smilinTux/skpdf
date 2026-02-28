"""Tests for SKPDF storage backends."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from skpdf.storage import (
    LocalBackend,
    NextcloudWebDAVBackend,
    GoogleDriveBackend,
    DropboxBackend,
    StorageBackend,
    StorageError,
    get_backend,
)


class TestLocalBackend:
    def test_name(self):
        backend = LocalBackend()
        assert backend.name == "local"

    def test_default_root(self):
        backend = LocalBackend()
        assert backend.root == Path.home() / "Documents"

    def test_custom_root(self, tmp_path):
        backend = LocalBackend(root=tmp_path)
        assert backend.root == tmp_path

    def test_store_copies_file(self, tmp_path):
        root = tmp_path / "storage"
        root.mkdir()
        backend = LocalBackend(root=root)

        source = tmp_path / "test.pdf"
        source.write_bytes(b"%PDF-fake-content")

        result = backend.store(source, "docs/test.pdf")
        assert (root / "docs" / "test.pdf").exists()
        assert (root / "docs" / "test.pdf").read_bytes() == b"%PDF-fake-content"
        assert str(root / "docs" / "test.pdf") == result

    def test_store_with_metadata(self, tmp_path):
        root = tmp_path / "storage"
        root.mkdir()
        backend = LocalBackend(root=root)

        source = tmp_path / "test.pdf"
        source.write_bytes(b"%PDF-content")

        backend.store(source, "docs/test.pdf", metadata_yaml="category: medical\n")
        assert (root / "docs" / "test.meta.yml").exists()
        assert "medical" in (root / "docs" / "test.meta.yml").read_text()

    def test_ensure_directory(self, tmp_path):
        backend = LocalBackend(root=tmp_path)
        backend.ensure_directory("@Reference/Medical/2026")
        assert (tmp_path / "@Reference" / "Medical" / "2026").is_dir()

    def test_exists(self, tmp_path):
        backend = LocalBackend(root=tmp_path)
        (tmp_path / "test.pdf").write_bytes(b"data")
        assert backend.exists("test.pdf") is True
        assert backend.exists("nonexistent.pdf") is False

    def test_store_creates_nested_dirs(self, tmp_path):
        root = tmp_path / "storage"
        root.mkdir()
        backend = LocalBackend(root=root)

        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        backend.store(source, "@Reference/Medical/2026/doc.pdf")
        assert (root / "@Reference" / "Medical" / "2026" / "doc.pdf").exists()


class TestNextcloudWebDAVBackend:
    def test_name(self):
        backend = NextcloudWebDAVBackend(
            base_url="https://cloud.example.com/dav/",
            username="user",
            password="pass",
        )
        assert backend.name == "nextcloud"

    def test_store_success(self, tmp_path):
        mock_requests = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_requests.put.return_value = mock_resp
        mock_requests.request.return_value = MagicMock(status_code=201)

        backend = NextcloudWebDAVBackend(
            base_url="https://cloud.example.com/dav",
            username="user",
            password="pass",
        )

        source = tmp_path / "test.pdf"
        source.write_bytes(b"%PDF")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = backend.store(source, "docs/test.pdf")
        assert result == "nextcloud:docs/test.pdf"

    def test_store_failure(self, tmp_path):
        mock_requests = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_requests.put.return_value = mock_resp
        mock_requests.request.return_value = MagicMock(status_code=201)

        backend = NextcloudWebDAVBackend(
            base_url="https://cloud.example.com/dav",
            username="user",
            password="pass",
        )

        source = tmp_path / "test.pdf"
        source.write_bytes(b"%PDF")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with pytest.raises(StorageError, match="500"):
                backend.store(source, "docs/test.pdf")


class TestGetBackend:
    def test_local(self):
        backend = get_backend("local")
        assert isinstance(backend, LocalBackend)

    def test_nextcloud(self):
        backend = get_backend(
            "nextcloud",
            base_url="https://example.com/dav",
            username="user",
            password="pass",
        )
        assert isinstance(backend, NextcloudWebDAVBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown storage backend"):
            get_backend("ftp")

    def test_all_valid_names(self):
        """All documented backend names are recognized."""
        assert get_backend("local")
        assert get_backend(
            "nextcloud", base_url="https://x", username="u", password="p"
        )
        assert get_backend("gdrive", credentials_path="/tmp/creds.json")
        assert get_backend("dropbox", access_token="abc")


class TestStorageBackendABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            StorageBackend()

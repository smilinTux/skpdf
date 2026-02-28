"""Integration tests: SKPDF → SKSeal → GTD filing bridge.

Tests the full sovereign document workflow:
  fill PDF form → sign with PGP → file to storage backend
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from skpdf.gtd_filer import GTDFiler
from skpdf.models import FilingResult, PDFField, FieldType
from skpdf.skseal_bridge import SignAndFileResult, sign_and_file, fill_sign_and_file
from skpdf.storage import LocalBackend


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

PASSPHRASE = "bridge-test-passphrase"


def _generate_pgp_key(name: str, email: str) -> tuple[str, str]:
    """Generate a test PGP keypair. Returns (private_armor, public_armor)."""
    import pgpy
    from pgpy.constants import (
        CompressionAlgorithm,
        HashAlgorithm,
        KeyFlags,
        PubKeyAlgorithm,
        SymmetricKeyAlgorithm,
    )

    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    uid = pgpy.PGPUID.new(name, email=email)
    key.add_uid(
        uid,
        usage={KeyFlags.Sign, KeyFlags.Certify},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.Uncompressed],
    )
    key.protect(PASSPHRASE, SymmetricKeyAlgorithm.AES256, HashAlgorithm.SHA256)
    return str(key), str(key.pubkey)


@pytest.fixture(scope="module")
def signer_keys():
    """PGP keys for the test signer (generated once per module)."""
    return _generate_pgp_key("Chef", "chef@smilintux.org")


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """Minimal well-formed PDF for signing tests."""
    pdf = tmp_path / "insurance_claim.pdf"
    pdf.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )
    return pdf


@pytest.fixture
def local_filer(tmp_path) -> GTDFiler:
    """GTDFiler backed by a local temp directory."""
    root = tmp_path / "Documents"
    root.mkdir()
    return GTDFiler(backends=[LocalBackend(root=root)])


# ---------------------------------------------------------------------------
# sign_and_file tests
# ---------------------------------------------------------------------------


class TestSignAndFile:
    def test_returns_sign_and_file_result(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        assert isinstance(result, SignAndFileResult)

    def test_document_id_is_uuid(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        import uuid
        uuid.UUID(result.document_id)  # raises if not a valid UUID

    def test_fingerprint_is_hex_string(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        assert len(result.fingerprint) == 40
        assert all(c in "0123456789ABCDEF" for c in result.fingerprint.upper())

    def test_signed_at_is_iso8601(self, signer_keys, sample_pdf, local_filer):
        from datetime import datetime

        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        # Should parse as a valid ISO datetime
        datetime.fromisoformat(result.signed_at)

    def test_signature_armor_is_pgp(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        assert "-----BEGIN PGP MESSAGE-----" in result.signature_armor

    def test_pdf_is_filed_to_storage(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        assert Path(result.filing.path).exists()

    def test_signed_tag_added_automatically(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
        )
        meta_path = Path(result.filing.metadata_path)
        import yaml
        content = yaml.safe_load(meta_path.read_text())
        assert "signed" in content["tags"]
        assert "signer:chef" in content["tags"]

    def test_user_tags_preserved(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
            tags=["claim", "2026"],
        )
        meta_path = Path(result.filing.metadata_path)
        import yaml
        content = yaml.safe_load(meta_path.read_text())
        assert "claim" in content["tags"]
        assert "2026" in content["tags"]

    def test_pdf_not_found_raises(self, signer_keys, local_filer):
        priv, pub = signer_keys
        with pytest.raises(FileNotFoundError):
            sign_and_file(
                pdf_path=Path("/nonexistent/file.pdf"),
                signer_name="Chef",
                signer_email="chef@smilintux.org",
                private_key_armor=priv,
                passphrase=PASSPHRASE,
                filer=local_filer,
            )

    def test_wrong_passphrase_raises(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        with pytest.raises(RuntimeError, match="PGP signing failed"):
            sign_and_file(
                pdf_path=sample_pdf,
                signer_name="Chef",
                signer_email="chef@smilintux.org",
                private_key_armor=priv,
                passphrase="wrong-passphrase",
                filer=local_filer,
            )

    def test_skseal_import_error_raises(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        with patch.dict("sys.modules", {"skseal": None, "skseal.engine": None}):
            with pytest.raises(ImportError, match="skseal is required"):
                sign_and_file(
                    pdf_path=sample_pdf,
                    signer_name="Chef",
                    signer_email="chef@smilintux.org",
                    private_key_armor=priv,
                    passphrase=PASSPHRASE,
                    filer=local_filer,
                )

    def test_auto_categorize_from_filename(self, signer_keys, sample_pdf, local_filer):
        """Filename 'insurance_claim.pdf' should auto-categorize as medical."""
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
        )
        assert result.filing.category == "medical"

    def test_category_override(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="legal",
        )
        assert result.filing.category == "legal"

    def test_source_in_metadata(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
            source="Blue Cross",
        )
        import yaml
        content = yaml.safe_load(Path(result.filing.metadata_path).read_text())
        assert content["source"] == "Blue Cross"

    def test_fill_stats_in_metadata(self, signer_keys, sample_pdf, local_filer):
        priv, pub = signer_keys
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="medical",
            fill_stats={"fields_filled": 8, "fields_auto": 7, "fields_manual": 1},
        )
        import yaml
        content = yaml.safe_load(Path(result.filing.metadata_path).read_text())
        assert content["fields_filled"] == 8

    def test_default_filer_uses_local_backend(self, signer_keys, sample_pdf):
        """When no filer provided, defaults to LocalBackend (~/Documents)."""
        priv, pub = signer_keys
        # Just verify it doesn't raise (filed to ~/Documents)
        result = sign_and_file(
            pdf_path=sample_pdf,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            category="medical",
        )
        assert isinstance(result, SignAndFileResult)
        # Clean up
        import shutil
        try:
            shutil.rmtree(Path(result.filing.path).parent)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# fill_sign_and_file tests
# ---------------------------------------------------------------------------


class TestFillSignAndFile:
    @pytest.fixture
    def blank_pdf(self, tmp_path) -> Path:
        """PDF with no AcroForm fields — fill_pdf will fill 0 fields."""
        pdf = tmp_path / "blank_tax_form.pdf"
        pdf.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
            b"xref\n0 4\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n190\n%%EOF"
        )
        return pdf

    @pytest.fixture
    def profile(self, tmp_path) -> Path:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(
            json.dumps({"name": "Chef", "tax_year": "2026", "amount": "1000"}),
            encoding="utf-8",
        )
        return profile_path

    def test_fill_sign_and_file_returns_result(
        self, signer_keys, blank_pdf, profile, local_filer
    ):
        priv, pub = signer_keys
        result = fill_sign_and_file(
            blank_pdf_path=blank_pdf,
            profile_path=profile,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
            category="financial",
        )
        assert isinstance(result, SignAndFileResult)
        assert result.filing.category == "financial"

    def test_fill_sign_and_file_filed_pdf_exists(
        self, signer_keys, blank_pdf, profile, local_filer
    ):
        priv, pub = signer_keys
        result = fill_sign_and_file(
            blank_pdf_path=blank_pdf,
            profile_path=profile,
            signer_name="Chef",
            signer_email="chef@smilintux.org",
            private_key_armor=priv,
            passphrase=PASSPHRASE,
            filer=local_filer,
        )
        assert Path(result.filing.path).exists()


# ---------------------------------------------------------------------------
# GoogleDriveBackend._write_metadata and .exists tests (mocked)
# ---------------------------------------------------------------------------


class TestGoogleDriveBackend:
    """Unit tests for the fixed GoogleDriveBackend methods (no real Drive creds)."""

    @pytest.fixture
    def gdrive(self, tmp_path):
        from skpdf.storage import GoogleDriveBackend
        backend = GoogleDriveBackend(
            credentials_path=str(tmp_path / "fake_creds.json"),
            root_folder_id="root",
        )
        return backend

    def test_exists_returns_false_without_creds(self, gdrive):
        """exists() should return False if Drive API fails (no real creds)."""
        result = gdrive.exists("@Reference/Medical/2026/test.pdf")
        assert result is False

    def test_write_metadata_calls_drive_api(self, gdrive):
        """_write_metadata should call files().create() when Drive is available."""
        import sys
        import types
        import unittest.mock as mock

        mock_file = {"id": "abc123"}
        mock_service = mock.MagicMock()
        mock_service.files().list().execute.return_value = {"files": [{"id": "folder1"}]}
        mock_service.files().create().execute.return_value = mock_file
        gdrive._service = mock_service

        # Provide a stub for googleapiclient.http.MediaInMemoryUpload
        fake_http_mod = types.ModuleType("googleapiclient.http")
        fake_http_mod.MediaInMemoryUpload = mock.MagicMock(return_value=mock.MagicMock())
        with mock.patch.dict(sys.modules, {"googleapiclient.http": fake_http_mod}):
            result = gdrive._write_metadata(
                "category: medical\n",
                "@Reference/Medical/2026/test.meta.yml",
            )
        assert result == "gdrive:abc123"

    def test_exists_returns_true_when_file_found(self, gdrive):
        """exists() returns True when Drive API finds the file."""
        import unittest.mock as mock

        mock_service = mock.MagicMock()
        # Parent folders exist, file exists
        mock_service.files().list().execute.return_value = {"files": [{"id": "x"}]}
        gdrive._service = mock_service

        result = gdrive.exists("@Reference/Medical/2026/test.pdf")
        assert result is True

    def test_exists_returns_false_when_folder_missing(self, gdrive):
        """exists() returns False when an intermediate folder is not found."""
        import unittest.mock as mock

        mock_service = mock.MagicMock()
        # No folders found
        mock_service.files().list().execute.return_value = {"files": []}
        gdrive._service = mock_service

        result = gdrive.exists("@Reference/Medical/2026/test.pdf")
        assert result is False

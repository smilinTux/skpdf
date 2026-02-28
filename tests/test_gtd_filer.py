"""Tests for SKPDF GTD filing system."""

import pytest
import yaml
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from skpdf.models import (
    Category,
    FilingResult,
    GTDStatus,
    PDFField,
    PDFMetadata,
    FieldType,
)
from skpdf.gtd_filer import GTDFiler
from skpdf.storage import LocalBackend, StorageError


@pytest.fixture
def tmp_root(tmp_path):
    """Temporary storage root directory."""
    root = tmp_path / "Documents"
    root.mkdir()
    return root


@pytest.fixture
def local_backend(tmp_root):
    return LocalBackend(root=tmp_root)


@pytest.fixture
def filer(local_backend):
    return GTDFiler(backends=[local_backend])


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a minimal PDF for testing."""
    pdf = tmp_path / "BC_Claim_Form_2026.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    return pdf


@pytest.fixture
def medical_fields():
    return [
        PDFField(name="patient_name", field_type=FieldType.TEXT),
        PDFField(name="insurance_policy", field_type=FieldType.TEXT, value="BC-12345"),
        PDFField(name="doctor_name", field_type=FieldType.TEXT),
        PDFField(name="ssn", field_type=FieldType.TEXT),
    ]


class TestCategorize:
    def test_medical_from_filename(self, filer, tmp_path):
        pdf = tmp_path / "insurance_claim_form.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "medical"

    def test_financial_from_filename(self, filer, tmp_path):
        pdf = tmp_path / "tax_1099_form.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "financial"

    def test_legal_from_filename(self, filer, tmp_path):
        pdf = tmp_path / "rental_agreement_contract.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "legal"

    def test_vehicle_from_filename(self, filer, tmp_path):
        pdf = tmp_path / "dmv_registration.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "vehicle"

    def test_uncategorized_generic_name(self, filer, tmp_path):
        pdf = tmp_path / "document_xyz.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "uncategorized"

    def test_fields_improve_categorization(self, filer, tmp_path, medical_fields):
        pdf = tmp_path / "form.pdf"
        pdf.write_bytes(b"%PDF")
        # "form" alone won't categorize, but medical fields will
        assert filer.categorize(pdf, medical_fields) == "medical"

    def test_housing_from_keywords(self, filer, tmp_path):
        pdf = tmp_path / "utility_bill_electric.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "housing"

    def test_government_from_filename(self, filer, tmp_path):
        pdf = tmp_path / "passport_application.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "government"

    def test_personal_from_filename(self, filer, tmp_path):
        pdf = tmp_path / "school_transcript.pdf"
        pdf.write_bytes(b"%PDF")
        assert filer.categorize(pdf) == "personal"


class TestSensitiveFields:
    def test_detects_ssn(self, filer):
        fields = [PDFField(name="SSN"), PDFField(name="first_name")]
        sensitive = filer.detect_sensitive_fields(fields)
        assert "SSN" in sensitive
        assert "first_name" not in sensitive

    def test_detects_account_number(self, filer):
        fields = [PDFField(name="account_number")]
        assert "account_number" in filer.detect_sensitive_fields(fields)

    def test_detects_social_security(self, filer):
        fields = [PDFField(name="social_security_number")]
        sensitive = filer.detect_sensitive_fields(fields)
        assert len(sensitive) == 1

    def test_no_false_positives(self, filer):
        fields = [
            PDFField(name="first_name"),
            PDFField(name="city"),
            PDFField(name="state"),
        ]
        assert filer.detect_sensitive_fields(fields) == []

    def test_detects_policy_number(self, filer):
        fields = [PDFField(name="policy_number")]
        assert len(filer.detect_sensitive_fields(fields)) == 1


class TestGenerateFilename:
    def test_basic_filename(self, filer, tmp_path):
        pdf = tmp_path / "claim_form.pdf"
        name = filer.generate_filename(
            pdf, "medical", date=datetime(2026, 2, 27)
        )
        assert name == "2026-02-27_claim-form.pdf"

    def test_with_source(self, filer, tmp_path):
        pdf = tmp_path / "claim.pdf"
        name = filer.generate_filename(
            pdf, "medical", source="Blue Cross", date=datetime(2026, 2, 27)
        )
        assert name == "2026-02-27_claim_blue-cross.pdf"

    def test_cleans_special_chars(self, filer, tmp_path):
        pdf = tmp_path / "My (Special) Form!.pdf"
        name = filer.generate_filename(
            pdf, "personal", date=datetime(2026, 1, 15)
        )
        assert name == "2026-01-15_my-special-form.pdf"


class TestBuildDestPath:
    def test_reference_path(self, filer):
        path = filer.build_dest_path(
            "2026-02-27_claim.pdf", "medical", "reference"
        )
        year = datetime.now().strftime("%Y")
        assert path == f"@Reference/Medical/{year}/2026-02-27_claim.pdf"

    def test_reference_with_subcategory(self, filer):
        year = datetime.now().strftime("%Y")
        path = filer.build_dest_path(
            "2026-02-27_1099.pdf", "financial", "reference", subcategory="tax"
        )
        assert path == f"@Reference/Financial/Tax/{year}/2026-02-27_1099.pdf"

    def test_inbox_path(self, filer):
        path = filer.build_dest_path("doc.pdf", "personal", "inbox")
        assert path == "@Inbox/doc.pdf"

    def test_action_path(self, filer):
        path = filer.build_dest_path("doc.pdf", "legal", "action")
        assert path == "@Action/Next-Actions/doc.pdf"

    def test_waiting_for_path(self, filer):
        path = filer.build_dest_path("doc.pdf", "medical", "waiting-for")
        assert path == "@Action/Waiting-For/doc.pdf"

    def test_archive_path(self, filer):
        path = filer.build_dest_path("doc.pdf", "personal", "archive")
        assert path == "@Archive/doc.pdf"


class TestGenerateMetadata:
    def test_basic_metadata(self, filer, sample_pdf):
        meta = filer.generate_metadata(
            pdf_path=sample_pdf,
            category="medical",
            gtd_status="reference",
            dest_paths=["local:@Reference/Medical/2026/test.pdf"],
        )
        assert isinstance(meta, PDFMetadata)
        assert meta.category == "medical"
        assert meta.status == "reference"
        assert meta.original_filename == "BC_Claim_Form_2026.pdf"
        assert "local:@Reference/Medical/2026/test.pdf" in meta.filed_to

    def test_metadata_with_fields(self, filer, sample_pdf, medical_fields):
        meta = filer.generate_metadata(
            pdf_path=sample_pdf,
            category="medical",
            gtd_status="reference",
            dest_paths=[],
            fields=medical_fields,
        )
        assert "ssn" in [f.lower() for f in meta.sensitive_fields]

    def test_metadata_tags(self, filer, sample_pdf):
        meta = filer.generate_metadata(
            pdf_path=sample_pdf,
            category="medical",
            gtd_status="reference",
            dest_paths=[],
            source="Blue Cross",
            tags=["claim", "2026"],
        )
        assert "medical" in meta.tags
        assert "blue-cross" in meta.tags
        assert "claim" in meta.tags

    def test_metadata_fill_stats(self, filer, sample_pdf):
        meta = filer.generate_metadata(
            pdf_path=sample_pdf,
            category="medical",
            gtd_status="reference",
            dest_paths=[],
            fill_stats={"fields_filled": 10, "fields_auto": 8, "fields_manual": 2},
        )
        assert meta.fields_filled == 10
        assert meta.fields_auto == 8
        assert meta.fields_manual == 2


class TestMetadataToYaml:
    def test_produces_valid_yaml(self, filer, sample_pdf):
        meta = filer.generate_metadata(
            pdf_path=sample_pdf,
            category="medical",
            gtd_status="reference",
            dest_paths=["local:@Reference/Medical/2026/test.pdf"],
        )
        yaml_str = filer.metadata_to_yaml(meta)
        parsed = yaml.safe_load(yaml_str)
        assert parsed["category"] == "medical"
        assert parsed["original_filename"] == "BC_Claim_Form_2026.pdf"


class TestFile:
    def test_file_to_local(self, filer, sample_pdf, tmp_root):
        result = filer.file(
            pdf_path=sample_pdf,
            category="medical",
            source="Blue Cross",
        )
        assert isinstance(result, FilingResult)
        assert result.category == "medical"
        assert result.gtd_status == "reference"
        assert len(result.destinations) == 1
        assert Path(result.path).exists()

    def test_auto_categorize(self, filer, sample_pdf):
        # "BC_Claim_Form_2026" should match medical via "insurance"/"claim" not present
        # but it has no medical keywords in stem, so may be uncategorized
        result = filer.file(pdf_path=sample_pdf)
        assert isinstance(result, FilingResult)
        assert result.category  # Should have some category

    def test_file_creates_metadata_sidecar(self, filer, sample_pdf, tmp_root):
        result = filer.file(
            pdf_path=sample_pdf,
            category="medical",
        )
        # Metadata sidecar should exist
        meta_path = Path(result.metadata_path)
        assert meta_path.exists()
        content = meta_path.read_text()
        assert "medical" in content

    def test_file_not_found(self, filer):
        with pytest.raises(FileNotFoundError):
            filer.file(pdf_path=Path("/nonexistent/file.pdf"))

    def test_file_with_gtd_status(self, filer, sample_pdf, tmp_root):
        result = filer.file(
            pdf_path=sample_pdf,
            category="legal",
            gtd_status="waiting-for",
        )
        assert result.gtd_status == "waiting-for"
        assert "@Action/Waiting-For" in result.path

    def test_file_with_tags(self, filer, sample_pdf, tmp_root):
        result = filer.file(
            pdf_path=sample_pdf,
            category="financial",
            tags=["tax", "2026"],
        )
        meta_path = Path(result.metadata_path)
        content = yaml.safe_load(meta_path.read_text())
        assert "tax" in content["tags"]
        assert "2026" in content["tags"]

    def test_all_backends_fail(self, sample_pdf):
        bad_backend = MagicMock()
        bad_backend.name = "broken"
        bad_backend.store.side_effect = RuntimeError("fail")
        filer = GTDFiler(backends=[bad_backend])

        with pytest.raises(StorageError, match="All storage backends failed"):
            filer.file(pdf_path=sample_pdf, category="personal")

    def test_multiple_backends(self, sample_pdf, tmp_path):
        root1 = tmp_path / "store1"
        root1.mkdir()
        root2 = tmp_path / "store2"
        root2.mkdir()

        filer = GTDFiler(backends=[LocalBackend(root=root1), LocalBackend(root=root2)])
        result = filer.file(pdf_path=sample_pdf, category="personal")
        assert len(result.destinations) == 2


class TestModels:
    def test_gtd_status_values(self):
        assert GTDStatus.INBOX == "inbox"
        assert GTDStatus.ACTION == "action"
        assert GTDStatus.WAITING_FOR == "waiting-for"
        assert GTDStatus.REFERENCE == "reference"
        assert GTDStatus.PROJECT == "project"
        assert GTDStatus.ARCHIVE == "archive"

    def test_category_values(self):
        assert Category.MEDICAL == "medical"
        assert Category.FINANCIAL == "financial"
        assert Category.LEGAL == "legal"
        assert Category.HOUSING == "housing"
        assert Category.VEHICLE == "vehicle"
        assert Category.GOVERNMENT == "government"
        assert Category.PERSONAL == "personal"
        assert Category.UNCATEGORIZED == "uncategorized"

    def test_filing_result_defaults(self):
        result = FilingResult(
            path="/tmp/test.pdf",
            category="medical",
            metadata_path="/tmp/test.meta.yml",
        )
        assert result.gtd_status == "reference"
        assert result.destinations == []

    def test_pdf_metadata_defaults(self):
        meta = PDFMetadata(
            original_filename="test.pdf",
            category="medical",
        )
        assert meta.status == "reference"
        assert meta.filed_by == "skpdf"
        assert meta.tags == []
        assert meta.sensitive_fields == []

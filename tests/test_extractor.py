"""Tests for SKPDF field extractor."""

import pytest

from skpdf.extractor import extract_fields


class TestExtractFields:
    """Tests for the extract_fields function."""

    def test_file_not_found(self):
        """Extracting from a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            extract_fields("/nonexistent/path.pdf")

    def test_non_form_pdf(self, tmp_path):
        """A PDF without form fields returns empty result."""
        # Reason: pypdf PdfWriter creates a valid PDF without any AcroForm
        from pypdf import PdfWriter

        pdf_path = tmp_path / "plain.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = extract_fields(pdf_path)
        assert result.total_fields == 0
        assert result.fields == []

    def test_extraction_result_filename(self, tmp_path):
        """Extraction result contains the correct filename."""
        from pypdf import PdfWriter

        pdf_path = tmp_path / "test_doc.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = extract_fields(pdf_path)
        assert result.filename == "test_doc.pdf"

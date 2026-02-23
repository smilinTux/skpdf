"""Tests for SKPDF form filler."""

import json

import pytest

from skpdf.filler import _normalize_key, _build_mapping, fill_pdf


class TestNormalizeKey:
    """Tests for _normalize_key helper."""

    def test_basic_lowercase(self):
        """Converts to lowercase and strips spaces."""
        assert _normalize_key("First Name") == "firstname"

    def test_strip_prefix(self):
        """Strips common PDF form prefixes."""
        assert _normalize_key("topmostSubForm[0].FullName") == "fullname"

    def test_separators(self):
        """Removes underscores, hyphens, dots."""
        assert _normalize_key("last_name") == "lastname"
        assert _normalize_key("zip-code") == "zipcode"


class TestBuildMapping:
    """Tests for _build_mapping helper."""

    def test_builds_normalized_mapping(self):
        """Profile keys are normalized in the mapping."""
        profile = {"First Name": "Dave", "last_name": "K"}
        mapping = _build_mapping(profile)
        assert mapping["firstname"] == "Dave"
        assert mapping["lastname"] == "K"


class TestFillPdf:
    """Tests for the fill_pdf function."""

    def test_missing_pdf(self, tmp_path):
        """Raises FileNotFoundError if PDF doesn't exist."""
        profile = tmp_path / "profile.json"
        profile.write_text("{}")
        with pytest.raises(FileNotFoundError):
            fill_pdf("/nonexistent.pdf", profile)

    def test_missing_profile(self, tmp_path):
        """Raises FileNotFoundError if profile doesn't exist."""
        from pypdf import PdfWriter

        pdf = tmp_path / "form.pdf"
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        with open(pdf, "wb") as f:
            writer.write(f)
        with pytest.raises(FileNotFoundError):
            fill_pdf(pdf, "/nonexistent.json")

    def test_fill_no_fields(self, tmp_path):
        """Filling a PDF with no fields fills zero fields."""
        from pypdf import PdfWriter

        pdf = tmp_path / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        with open(pdf, "wb") as f:
            writer.write(f)

        profile = tmp_path / "profile.json"
        profile.write_text(json.dumps({"name": "Dave"}))

        result = fill_pdf(pdf, profile)
        assert result.fields_filled == 0
        assert result.fields_total == 0

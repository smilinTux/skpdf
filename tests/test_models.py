"""Tests for SKPDF models."""

from skpdf.models import (
    ExtractionResult,
    FieldType,
    FillResult,
    PDFField,
)


def test_pdf_field_defaults():
    """Test PDFField with minimal required fields."""
    field = PDFField(name="first_name")
    assert field.name == "first_name"
    assert field.field_type == FieldType.TEXT
    assert field.value is None
    assert field.options == []
    assert field.page == 0
    assert field.required is False


def test_pdf_field_full():
    """Test PDFField with all fields populated."""
    field = PDFField(
        name="state",
        field_type=FieldType.DROPDOWN,
        value="CA",
        options=["CA", "NY", "TX"],
        page=2,
        required=True,
    )
    assert field.field_type == FieldType.DROPDOWN
    assert len(field.options) == 3
    assert field.required is True


def test_extraction_result_empty():
    """Test ExtractionResult with no fields."""
    result = ExtractionResult(filename="empty.pdf", total_fields=0, fields=[])
    assert result.total_fields == 0
    assert result.fields == []


def test_fill_result():
    """Test FillResult model."""
    result = FillResult(
        output_path="/tmp/filled.pdf",
        fields_filled=5,
        fields_skipped=2,
        fields_total=7,
    )
    assert result.fields_filled == 5
    assert result.fields_skipped == 2


def test_field_type_values():
    """Test all FieldType enum values exist."""
    assert FieldType.TEXT == "text"
    assert FieldType.CHECKBOX == "checkbox"
    assert FieldType.RADIO == "radio"
    assert FieldType.DROPDOWN == "dropdown"
    assert FieldType.SIGNATURE == "signature"
    assert FieldType.UNKNOWN == "unknown"

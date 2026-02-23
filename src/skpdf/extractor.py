"""
PDF field extraction using pypdf.

Extracts AcroForm fields from PDF files and returns structured data.
"""

from pathlib import Path
from typing import Union

from pypdf import PdfReader
from pypdf.constants import AnnotationDictionaryAttributes as ADA

from .models import ExtractionResult, FieldType, PDFField


def _detect_field_type(field: dict) -> FieldType:
    """Detect the field type from PDF annotation dictionary.

    Args:
        field: Raw PDF field dictionary.

    Returns:
        FieldType: Detected type of the field.
    """
    ft = field.get("/FT", "")
    if ft == "/Tx":
        return FieldType.TEXT
    elif ft == "/Btn":
        return FieldType.CHECKBOX
    elif ft == "/Ch":
        return FieldType.DROPDOWN
    elif ft == "/Sig":
        return FieldType.SIGNATURE
    return FieldType.UNKNOWN


def _extract_options(field: dict) -> list[str]:
    """Extract options from dropdown/radio fields.

    Args:
        field: Raw PDF field dictionary.

    Returns:
        list[str]: Available options.
    """
    opts = field.get("/Opt", [])
    result = []
    for opt in opts:
        if isinstance(opt, list) and len(opt) >= 2:
            result.append(str(opt[1]))
        else:
            result.append(str(opt))
    return result


def extract_fields(pdf_path: Union[str, Path]) -> ExtractionResult:
    """Extract all form fields from a PDF file.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        ExtractionResult: Structured extraction results.

    Raises:
        FileNotFoundError: If the PDF file doesn't exist.
        ValueError: If the PDF has no form fields.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    fields: list[PDFField] = []

    if reader.get_fields() is None:
        return ExtractionResult(
            filename=pdf_path.name,
            total_fields=0,
            fields=[],
        )

    for name, field_obj in reader.get_fields().items():
        raw = field_obj if isinstance(field_obj, dict) else {}

        field_type = _detect_field_type(raw)
        value = raw.get("/V")
        if value and hasattr(value, "get_object"):
            value = str(value)

        options = _extract_options(raw) if field_type == FieldType.DROPDOWN else []

        # Reason: /Ff bit 2 indicates required field in PDF spec
        flags = raw.get("/Ff", 0)
        required = bool(flags & 2) if isinstance(flags, int) else False

        fields.append(
            PDFField(
                name=name,
                field_type=field_type,
                value=value,
                options=options,
                required=required,
            )
        )

    return ExtractionResult(
        filename=pdf_path.name,
        total_fields=len(fields),
        fields=fields,
    )

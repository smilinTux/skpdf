"""
Pydantic models for SKPDF field extraction and filling.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    """PDF form field types."""

    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    SIGNATURE = "signature"
    UNKNOWN = "unknown"


class PDFField(BaseModel):
    """Represents a single form field extracted from a PDF.

    Args:
        name: The internal field name from the PDF.
        field_type: The type of form field.
        value: Current value of the field (if any).
        options: Available options for dropdown/radio fields.
        page: Page number where the field appears (0-indexed).
        required: Whether the field is marked required.
    """

    name: str
    field_type: FieldType = FieldType.TEXT
    value: Optional[Any] = None
    options: list[str] = Field(default_factory=list)
    page: int = 0
    required: bool = False


class ExtractionResult(BaseModel):
    """Result of extracting fields from a PDF.

    Args:
        filename: Source PDF filename.
        total_fields: Number of fields found.
        fields: List of extracted field details.
    """

    filename: str
    total_fields: int
    fields: list[PDFField]


class FillResult(BaseModel):
    """Result of filling a PDF form.

    Args:
        output_path: Path to the filled PDF.
        fields_filled: Number of fields that were filled.
        fields_skipped: Number of fields not matched by profile.
        fields_total: Total number of fields in the form.
    """

    output_path: str
    fields_filled: int
    fields_skipped: int
    fields_total: int

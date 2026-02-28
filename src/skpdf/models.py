"""
Pydantic models for SKPDF field extraction and filling.
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
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


class GTDStatus(str, Enum):
    """GTD workflow statuses."""

    INBOX = "inbox"
    ACTION = "action"
    WAITING_FOR = "waiting-for"
    REFERENCE = "reference"
    PROJECT = "project"
    ARCHIVE = "archive"


class Category(str, Enum):
    """Document filing categories."""

    MEDICAL = "medical"
    FINANCIAL = "financial"
    LEGAL = "legal"
    HOUSING = "housing"
    VEHICLE = "vehicle"
    GOVERNMENT = "government"
    PERSONAL = "personal"
    UNCATEGORIZED = "uncategorized"


class PDFMetadata(BaseModel):
    """Metadata sidecar for a filed PDF.

    Written as YAML alongside the filed document for searchability
    and audit trails.
    """

    original_filename: str
    filed_date: datetime = Field(default_factory=lambda: datetime.now())
    category: str
    subcategory: Optional[str] = None
    source: Optional[str] = None
    status: str = GTDStatus.REFERENCE.value
    follow_up_date: Optional[datetime] = None
    fields_filled: int = 0
    fields_auto: int = 0
    fields_manual: int = 0
    sensitive_fields: list[str] = Field(default_factory=list)
    filed_by: str = "skpdf"
    filed_to: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class FilingResult(BaseModel):
    """Result of filing a PDF to storage.

    Args:
        path: Final path of the filed document.
        category: Detected or specified category.
        gtd_status: GTD workflow status applied.
        metadata_path: Path to the YAML metadata sidecar.
        filed_at: Timestamp of filing.
        destinations: List of backends the file was sent to.
    """

    path: str
    category: str
    gtd_status: str = GTDStatus.REFERENCE.value
    metadata_path: str
    filed_at: datetime = Field(default_factory=lambda: datetime.now())
    destinations: list[str] = Field(default_factory=list)

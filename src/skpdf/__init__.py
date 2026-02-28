"""
SKPDF - PDF field extraction, auto-fill, and GTD filing.

Copyright (C) 2025 smilinTux
Licensed under GPL-3.0-or-later.
"""

__version__ = "0.2.0"

from .models import (
    Category,
    ExtractionResult,
    FieldType,
    FilingResult,
    FillResult,
    GTDStatus,
    PDFField,
    PDFMetadata,
)
from .storage import (
    DropboxBackend,
    GoogleDriveBackend,
    LocalBackend,
    NextcloudWebDAVBackend,
    StorageBackend,
    StorageError,
    get_backend,
)
from .gtd_filer import GTDFiler

__all__ = [
    "Category",
    "DropboxBackend",
    "ExtractionResult",
    "FieldType",
    "FilingResult",
    "FillResult",
    "GTDFiler",
    "GTDStatus",
    "GoogleDriveBackend",
    "LocalBackend",
    "NextcloudWebDAVBackend",
    "PDFField",
    "PDFMetadata",
    "StorageBackend",
    "StorageError",
    "get_backend",
    "__version__",
]

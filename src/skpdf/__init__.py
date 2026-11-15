"""
SKPDF - PDF field extraction, auto-fill, and GTD filing.

Copyright (C) 2025 smilinTux
Licensed under GPL-3.0-or-later.
"""

__version__ = "0.2.0"

from .gtd_filer import GTDFiler
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
from .skseal_bridge import SignAndFileResult, fill_sign_and_file, sign_and_file
from .storage import (
    DropboxBackend,
    GoogleDriveBackend,
    LocalBackend,
    NextcloudWebDAVBackend,
    StorageBackend,
    StorageError,
    get_backend,
)

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
    "SignAndFileResult",
    "fill_sign_and_file",
    "sign_and_file",
    "__version__",
]

"""
GTD-based PDF filing system.

Categorizes filled PDFs and files them to storage backends using
Getting Things Done (GTD) organizational principles.

GTD folder structure:
    @Inbox/           — New/unprocessed
    @Action/          — Needs follow-up
      Waiting-For/    — Sent, awaiting response
      Next-Actions/   — Your next steps
    @Reference/       — Filed for future reference
      Medical/
      Financial/
      Legal/
      Housing/
      Vehicle/
      Government/
      Personal/
    @Projects/        — Active projects
    @Archive/         — Completed
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .models import (
    Category,
    ExtractionResult,
    FilingResult,
    GTDStatus,
    PDFField,
    PDFMetadata,
)
from .storage import LocalBackend, StorageBackend

logger = logging.getLogger("skpdf.gtd_filer")

# Category keyword mappings for auto-categorization
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    Category.MEDICAL.value: [
        "insurance", "doctor", "hospital", "pharmacy", "health",
        "medical", "patient", "diagnosis", "prescription", "clinic",
        "dental", "vision", "therapy", "copay", "deductible",
        "blue cross", "aetna", "cigna", "united health", "kaiser",
    ],
    Category.FINANCIAL.value: [
        "tax", "bank", "loan", "credit", "investment", "1099",
        "w-2", "w2", "irs", "income", "deposit", "withdrawal",
        "mortgage", "interest", "dividend", "portfolio", "401k",
        "savings", "checking", "routing", "account number",
    ],
    Category.LEGAL.value: [
        "contract", "agreement", "court", "attorney", "will",
        "power of attorney", "notary", "affidavit", "deposition",
        "settlement", "lawsuit", "arbitration", "legal",
    ],
    Category.HOUSING.value: [
        "lease", "rent", "mortgage", "utility", "hoa",
        "landlord", "tenant", "property", "electric", "gas",
        "water", "sewer", "maintenance", "inspection",
    ],
    Category.VEHICLE.value: [
        "dmv", "registration", "title", "vin", "odometer",
        "vehicle", "auto", "car", "truck", "motorcycle",
        "license plate", "emission", "smog",
    ],
    Category.GOVERNMENT.value: [
        "irs", "ssa", "passport", "visa", "license",
        "social security", "citizenship", "immigration",
        "permit", "census", "voter", "selective service",
    ],
    Category.PERSONAL.value: [
        "school", "employment", "certificate", "resume",
        "transcript", "diploma", "birth", "marriage", "death",
        "adoption", "membership",
    ],
}

# Sensitive field patterns to flag in metadata
SENSITIVE_PATTERNS = [
    r"ss[n_\- ]?(?:number)?",
    r"social.?security",
    r"tax.?id",
    r"ein",
    r"policy.?number",
    r"account.?(?:number|num|no)",
    r"routing.?(?:number|num|no)",
    r"credit.?card",
    r"passport.?(?:number|num|no)",
    r"driver.?license",
    r"dob|date.?of.?birth",
]

# GTD status to folder mapping
GTD_FOLDERS: dict[str, str] = {
    GTDStatus.INBOX.value: "@Inbox",
    GTDStatus.ACTION.value: "@Action/Next-Actions",
    GTDStatus.WAITING_FOR.value: "@Action/Waiting-For",
    GTDStatus.REFERENCE.value: "@Reference",
    GTDStatus.PROJECT.value: "@Projects",
    GTDStatus.ARCHIVE.value: "@Archive",
}


class GTDFiler:
    """File PDFs using GTD (Getting Things Done) principles.

    Categorizes documents based on form field analysis, generates
    standardized filenames, writes metadata sidecars, and stores
    to one or more storage backends.

    Args:
        backends: Storage backends to file to. Defaults to LocalBackend.
        filed_by: Identity of the filer (for metadata audit).
    """

    def __init__(
        self,
        backends: Optional[list[StorageBackend]] = None,
        filed_by: str = "skpdf",
    ):
        self._backends = backends or [LocalBackend()]
        self._filed_by = filed_by

    @property
    def backends(self) -> list[StorageBackend]:
        return self._backends

    def categorize(
        self,
        pdf_path: Path,
        fields: Optional[list[PDFField]] = None,
    ) -> str:
        """Determine category based on filename and field content.

        Scans the PDF filename and extracted field names/values for
        category keywords. Returns the best match or 'uncategorized'.

        Args:
            pdf_path: Path to the PDF file.
            fields: Extracted form fields (optional, improves accuracy).

        Returns:
            str: Category name (e.g., 'medical', 'financial').
        """
        text_parts: list[str] = []

        # Filename is a strong signal
        text_parts.append(pdf_path.stem.lower().replace("_", " ").replace("-", " "))

        # Field names and values provide additional context
        if fields:
            for field in fields:
                text_parts.append(field.name.lower())
                if field.value:
                    text_parts.append(str(field.value).lower())

        combined = " ".join(text_parts)

        scores: dict[str, int] = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in combined)
            if score > 0:
                scores[category] = score

        if not scores:
            return Category.UNCATEGORIZED.value

        return max(scores, key=scores.get)

    def detect_sensitive_fields(self, fields: list[PDFField]) -> list[str]:
        """Find fields that likely contain sensitive data.

        Args:
            fields: Extracted form fields.

        Returns:
            list[str]: Names of fields flagged as sensitive.
        """
        sensitive = []
        for field in fields:
            name_lower = field.name.lower().replace("_", " ").replace("-", " ")
            for pattern in SENSITIVE_PATTERNS:
                if re.search(pattern, name_lower, re.IGNORECASE):
                    sensitive.append(field.name)
                    break
        return sensitive

    def generate_filename(
        self,
        pdf_path: Path,
        category: str,
        source: Optional[str] = None,
        date: Optional[datetime] = None,
    ) -> str:
        """Generate a standardized GTD filename.

        Format: YYYY-MM-DD_description_source.pdf

        Args:
            pdf_path: Original PDF path.
            category: Filing category.
            source: Document source/issuer (optional).
            date: Document date (optional, defaults to today).

        Returns:
            str: Standardized filename.
        """
        date = date or datetime.now()
        date_str = date.strftime("%Y-%m-%d")

        # Clean the stem for use as description
        stem = pdf_path.stem.lower()
        stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")

        parts = [date_str, stem]
        if source:
            clean_source = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
            parts.append(clean_source)

        return "_".join(parts) + ".pdf"

    def build_dest_path(
        self,
        filename: str,
        category: str,
        gtd_status: str = GTDStatus.REFERENCE.value,
        subcategory: Optional[str] = None,
    ) -> str:
        """Build the destination path within GTD folder structure.

        Args:
            filename: Standardized filename.
            category: Filing category.
            gtd_status: GTD status for folder placement.
            subcategory: Optional subcategory folder.

        Returns:
            str: Relative path like @Reference/Medical/2026/filename.pdf
        """
        gtd_folder = GTD_FOLDERS.get(gtd_status, "@Reference")
        year = datetime.now().strftime("%Y")

        if gtd_status == GTDStatus.REFERENCE.value:
            cat_title = category.title()
            if subcategory:
                return f"{gtd_folder}/{cat_title}/{subcategory.title()}/{year}/{filename}"
            return f"{gtd_folder}/{cat_title}/{year}/{filename}"
        else:
            return f"{gtd_folder}/{filename}"

    def generate_metadata(
        self,
        pdf_path: Path,
        category: str,
        gtd_status: str,
        dest_paths: list[str],
        fields: Optional[list[PDFField]] = None,
        fill_stats: Optional[dict] = None,
        source: Optional[str] = None,
        subcategory: Optional[str] = None,
        follow_up_date: Optional[datetime] = None,
        tags: Optional[list[str]] = None,
    ) -> PDFMetadata:
        """Generate metadata for a filed PDF.

        Args:
            pdf_path: Original PDF path.
            category: Filing category.
            gtd_status: GTD workflow status.
            dest_paths: List of destination paths/URIs.
            fields: Extracted fields (for sensitive detection).
            fill_stats: Fill operation stats (fields_filled, etc.).
            source: Document source/issuer.
            subcategory: Filing subcategory.
            follow_up_date: Optional follow-up date.
            tags: Additional tags.

        Returns:
            PDFMetadata: Complete metadata for the sidecar file.
        """
        sensitive = self.detect_sensitive_fields(fields) if fields else []

        auto_tags = [category]
        if subcategory:
            auto_tags.append(subcategory)
        auto_tags.append(datetime.now().strftime("%Y"))
        if source:
            auto_tags.append(source.lower().replace(" ", "-"))
        if tags:
            auto_tags.extend(tags)

        return PDFMetadata(
            original_filename=pdf_path.name,
            category=category,
            subcategory=subcategory,
            source=source,
            status=gtd_status,
            follow_up_date=follow_up_date,
            fields_filled=fill_stats.get("fields_filled", 0) if fill_stats else 0,
            fields_auto=fill_stats.get("fields_auto", 0) if fill_stats else 0,
            fields_manual=fill_stats.get("fields_manual", 0) if fill_stats else 0,
            sensitive_fields=sensitive,
            filed_by=self._filed_by,
            filed_to=dest_paths,
            tags=auto_tags,
        )

    def metadata_to_yaml(self, metadata: PDFMetadata) -> str:
        """Serialize metadata to YAML string.

        Args:
            metadata: PDFMetadata instance.

        Returns:
            str: YAML-formatted metadata.
        """
        data = metadata.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def file(
        self,
        pdf_path: Path,
        category: Optional[str] = None,
        gtd_status: str = GTDStatus.REFERENCE.value,
        source: Optional[str] = None,
        subcategory: Optional[str] = None,
        fields: Optional[list[PDFField]] = None,
        fill_stats: Optional[dict] = None,
        follow_up_date: Optional[datetime] = None,
        tags: Optional[list[str]] = None,
    ) -> FilingResult:
        """File a PDF to all configured storage backends.

        Auto-categorizes if no category provided. Generates standardized
        filename, metadata sidecar, and stores to all backends.

        Args:
            pdf_path: Path to the PDF to file.
            category: Category override (auto-detected if not provided).
            gtd_status: GTD status (default: reference).
            source: Document source/issuer.
            subcategory: Optional subcategory.
            fields: Extracted form fields.
            fill_stats: Fill operation statistics.
            follow_up_date: Follow-up date for action items.
            tags: Additional tags.

        Returns:
            FilingResult: Summary of the filing operation.

        Raises:
            FileNotFoundError: If the PDF doesn't exist.
            StorageError: If all backends fail.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Auto-categorize if needed
        if category is None:
            category = self.categorize(pdf_path, fields)

        # Generate standardized filename and destination path
        filename = self.generate_filename(pdf_path, category, source)
        dest_path = self.build_dest_path(filename, category, gtd_status, subcategory)

        # Store to all backends and collect destination URIs
        dest_uris: list[str] = []
        primary_path = ""
        metadata_path = ""

        for backend in self._backends:
            try:
                uri = backend.store(pdf_path, dest_path)
                dest_uris.append(f"{backend.name}:{dest_path}")
                if not primary_path:
                    primary_path = uri
            except Exception as exc:
                logger.error(
                    "Failed to store to %s: %s", backend.name, exc
                )

        if not dest_uris:
            from .storage import StorageError
            raise StorageError("All storage backends failed")

        # Generate and store metadata
        metadata = self.generate_metadata(
            pdf_path=pdf_path,
            category=category,
            gtd_status=gtd_status,
            dest_paths=dest_uris,
            fields=fields,
            fill_stats=fill_stats,
            source=source,
            subcategory=subcategory,
            follow_up_date=follow_up_date,
            tags=tags,
        )
        metadata_yaml = self.metadata_to_yaml(metadata)

        # Store metadata sidecar to first successful backend
        meta_dest = dest_path.rsplit(".", 1)[0] + ".meta.yml"
        for backend in self._backends:
            try:
                metadata_path = backend.store_metadata(metadata_yaml, dest_path)
                break
            except Exception:
                pass

        if not metadata_path:
            metadata_path = meta_dest

        return FilingResult(
            path=primary_path,
            category=category,
            gtd_status=gtd_status,
            metadata_path=metadata_path,
            destinations=dest_uris,
        )

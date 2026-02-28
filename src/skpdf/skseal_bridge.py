"""SKPDF → SKSeal → GTD integration bridge.

Provides the high-level `sign_and_file` function that wires:

  1. SKPDF form filling (skpdf.filler.fill_pdf)
  2. SKSeal PGP document signing (skseal.engine.SealEngine)
  3. GTD filing to storage backends (skpdf.gtd_filer.GTDFiler)

This is the primary integration point for the sovereign document workflow:
fill a form → sign with your key → file to your sovereign storage.

Example::

    from skpdf.filler import fill_pdf
    from skpdf.skseal_bridge import sign_and_file
    from skpdf.storage import NextcloudWebDAVBackend
    from skpdf.gtd_filer import GTDFiler

    # 1. Fill the form
    fill = fill_pdf("blank.pdf", "profile.json", "filled.pdf")

    # 2. Sign and file
    result = sign_and_file(
        pdf_path="filled.pdf",
        signer_name="Chef",
        signer_email="chef@smilintux.org",
        private_key_armor=my_pgp_key,
        passphrase="my-passphrase",
        filer=GTDFiler(backends=[NextcloudWebDAVBackend(...)]),
        source="Blue Cross",
        tags=["claim"],
    )

    print(result.document_id)   # SKSeal document UUID
    print(result.fingerprint)   # PGP fingerprint used
    print(result.filing.path)   # Where the PDF was filed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .gtd_filer import GTDFiler
from .models import FilingResult, PDFField

logger = logging.getLogger("skpdf.skseal_bridge")


@dataclass
class SignAndFileResult:
    """Result of a sign-and-file operation.

    Attributes:
        document_id: SKSeal document UUID.
        filing: GTD filing result (path, category, destinations).
        fingerprint: PGP fingerprint of the key used to sign.
        signed_at: ISO-8601 timestamp of the signature.
        signature_armor: ASCII-armored PGP signature.
    """

    document_id: str
    filing: FilingResult
    fingerprint: str
    signed_at: str
    signature_armor: str


def sign_and_file(
    pdf_path: Path,
    signer_name: str,
    signer_email: str,
    private_key_armor: str,
    passphrase: str,
    filer: Optional[GTDFiler] = None,
    category: Optional[str] = None,
    gtd_status: str = "reference",
    source: Optional[str] = None,
    subcategory: Optional[str] = None,
    tags: Optional[list[str]] = None,
    fields: Optional[list[PDFField]] = None,
    fill_stats: Optional[dict] = None,
    title: Optional[str] = None,
) -> SignAndFileResult:
    """Sign a filled PDF with SKSeal and file it via GTD.

    High-level integration that wires skpdf → skseal → GTD filing.
    The PDF hash is signed client-side using the signer's PGP key;
    only the signature (never the private key) is persisted.

    Args:
        pdf_path: Path to the filled PDF to sign and file.
        signer_name: Signer's display name.
        signer_email: Signer's email address.
        private_key_armor: ASCII-armored PGP private key (passphrase-protected).
        passphrase: Passphrase to unlock the private key.
        filer: GTDFiler instance. Defaults to LocalBackend under ~/Documents.
        category: Filing category override (auto-detected from filename/fields if None).
        gtd_status: GTD workflow status (default: 'reference').
        source: Document source/issuer for metadata.
        subcategory: Filing subcategory (e.g., 'tax' under 'financial').
        tags: Additional filing tags.
        fields: Extracted PDF fields for categorization and sensitive data detection.
        fill_stats: Fill operation stats dict (fields_filled, fields_auto, fields_manual).
        title: Document title. Defaults to a humanized version of the PDF filename.

    Returns:
        SignAndFileResult containing SKSeal document ID, filing result,
        PGP fingerprint, signature timestamp, and the armored signature.

    Raises:
        ImportError: If the ``skseal`` package is not installed.
        FileNotFoundError: If the PDF file does not exist.
        RuntimeError: If PGP signing fails.
        StorageError: If all configured storage backends fail.
    """
    try:
        from skseal.engine import SealEngine
        from skseal.models import Document, DocumentStatus, Signer
    except ImportError as exc:
        raise ImportError(
            "skseal is required for sign_and_file. "
            "Install it with: pip install skseal"
        ) from exc

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    filer = filer or GTDFiler()
    engine = SealEngine()

    # Humanize the title from the filename if not provided
    doc_title = title or pdf_path.stem.replace("_", " ").replace("-", " ").title()

    # Hash the PDF — this is what gets signed
    pdf_data = pdf_path.read_bytes()
    pdf_hash = engine.hash_bytes(pdf_data)

    # Build the SKSeal signing document
    signer = Signer(
        name=signer_name,
        email=signer_email,
        fingerprint="pending",
    )
    document = Document(
        title=doc_title,
        signers=[signer],
        status=DocumentStatus.PENDING,
        pdf_hash=pdf_hash,
    )

    # Sign — private key used in memory, never persisted
    logger.info("Signing '%s' as %s <%s>", pdf_path.name, signer_name, signer_email)
    signed_doc = engine.sign_document(
        document=document,
        signer_id=signer.signer_id,
        private_key_armor=private_key_armor,
        passphrase=passphrase,
        pdf_data=pdf_data,
    )

    sig = signed_doc.signatures[0]
    logger.info("Signed with key %s...", sig.fingerprint[:16])

    # Enrich tags with signing provenance
    filing_tags = list(tags or [])
    filing_tags.append("signed")
    filing_tags.append(f"signer:{signer_name.lower().replace(' ', '-')}")

    # File via GTD
    filing = filer.file(
        pdf_path=pdf_path,
        category=category,
        gtd_status=gtd_status,
        source=source,
        subcategory=subcategory,
        fields=fields,
        fill_stats=fill_stats,
        tags=filing_tags,
    )

    logger.info(
        "Filed '%s' -> %s (category=%s)",
        pdf_path.name,
        filing.destinations,
        filing.category,
    )

    return SignAndFileResult(
        document_id=signed_doc.document_id,
        filing=filing,
        fingerprint=sig.fingerprint,
        signed_at=sig.signed_at.isoformat(),
        signature_armor=sig.signature_armor,
    )


def fill_sign_and_file(
    blank_pdf_path: Path,
    profile_path: Path,
    signer_name: str,
    signer_email: str,
    private_key_armor: str,
    passphrase: str,
    output_path: Optional[Path] = None,
    filer: Optional[GTDFiler] = None,
    category: Optional[str] = None,
    gtd_status: str = "reference",
    source: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> SignAndFileResult:
    """Fill, sign, and file a PDF in one call.

    Convenience wrapper that chains skpdf.filler.fill_pdf → sign_and_file.

    Args:
        blank_pdf_path: Path to the blank PDF form.
        profile_path: Path to the JSON fill profile.
        signer_name: Signer's display name.
        signer_email: Signer's email address.
        private_key_armor: ASCII-armored PGP private key.
        passphrase: Passphrase to unlock the private key.
        output_path: Path for the filled PDF. Defaults to <input>_filled.pdf.
        filer: GTDFiler instance. Defaults to LocalBackend.
        category: Filing category override.
        gtd_status: GTD workflow status (default: 'reference').
        source: Document source/issuer.
        tags: Additional filing tags.

    Returns:
        SignAndFileResult with SKSeal document ID, filing result, and signature info.
    """
    from .filler import fill_pdf

    fill_result = fill_pdf(blank_pdf_path, profile_path, output_path)
    filled_path = Path(fill_result.output_path)

    fill_stats = {
        "fields_filled": fill_result.fields_filled,
        "fields_auto": fill_result.fields_filled,
        "fields_manual": 0,
    }

    return sign_and_file(
        pdf_path=filled_path,
        signer_name=signer_name,
        signer_email=signer_email,
        private_key_armor=private_key_armor,
        passphrase=passphrase,
        filer=filer,
        category=category,
        gtd_status=gtd_status,
        source=source,
        tags=tags,
        fill_stats=fill_stats,
    )

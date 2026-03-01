"""
PDF form filler using pypdf.

Fills AcroForm fields in PDF files from a JSON profile.
"""

import json
from pathlib import Path
from typing import Any, Union

from pypdf import PdfReader, PdfWriter

from .models import FillResult


def _normalize_key(key: str) -> str:
    """Normalize a field name for fuzzy matching.

    Strips common prefixes, converts to lowercase, replaces separators.

    Args:
        key: Raw field name.

    Returns:
        str: Normalized key for comparison.
    """
    key = key.lower().strip()
    for prefix in ("form1[0].", "topmostsubform[0].", "page1[0]."):
        if key.startswith(prefix):
            key = key[len(prefix) :]
    key = key.replace("_", "").replace("-", "").replace(" ", "").replace(".", "")
    return key


def _build_mapping(profile: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized lookup table from profile data.

    Preserves original value types (booleans for checkboxes, strings for text).

    Args:
        profile: Raw profile key-value pairs.

    Returns:
        dict: Normalized key -> original value (type preserved).
    """
    mapping: dict[str, Any] = {}
    for k, v in profile.items():
        mapping[_normalize_key(k)] = v
    return mapping


def _is_truthy(value: Any) -> bool:
    """Check if a value represents 'checked' for a checkbox."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "/yes", "on", "/on")
    return bool(value)


def _get_checkbox_on_states(writer: PdfWriter) -> dict[str, str]:
    """Find the 'on' appearance state name for each checkbox field.

    Most checkboxes use /Yes, but some use /1, /On, etc.
    Inspects the /AP/N dictionary to find the non-/Off state.
    """
    states: dict[str, str] = {}
    for page in writer.pages:
        annots = page.get("/Annots", [])
        for annot_ref in annots:
            annot = annot_ref.get_object()
            parent = annot.get("/Parent")
            parent_obj = parent.get_object() if parent else annot
            ft = annot.get("/FT") or parent_obj.get("/FT", "")
            name = annot.get("/T") or parent_obj.get("/T", "")

            if ft != "/Btn":
                continue

            ap = annot.get("/AP")
            if not ap:
                continue
            n = ap.get_object().get("/N")
            if not n or not hasattr(n.get_object(), "keys"):
                continue

            for key in n.get_object().keys():
                if key != "/Off":
                    states[str(name)] = str(key)
                    break
    return states


def fill_pdf(
    pdf_path: Union[str, Path],
    profile_path: Union[str, Path],
    output_path: Union[str, Path, None] = None,
) -> FillResult:
    """Fill a PDF form from a JSON profile.

    Args:
        pdf_path: Path to the input PDF with form fields.
        profile_path: Path to a JSON file containing field values.
        output_path: Path for the filled PDF. Defaults to <input>_filled.pdf.

    Returns:
        FillResult: Summary of the fill operation.

    Raises:
        FileNotFoundError: If input files don't exist.
        json.JSONDecodeError: If profile is not valid JSON.
    """
    pdf_path = Path(pdf_path)
    profile_path = Path(profile_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with open(profile_path) as f:
        profile = json.load(f)

    if output_path is None:
        output_path = pdf_path.parent / f"{pdf_path.stem}_filled.pdf"
    output_path = Path(output_path)

    reader = PdfReader(pdf_path)
    writer = PdfWriter(clone_from=reader)

    raw_fields = reader.get_fields() or {}
    mapping = _build_mapping(profile)

    # Build field type lookup and checkbox on-states
    field_types: dict[str, str] = {}
    for name, field in raw_fields.items():
        field_types[name] = field.get("/FT", "")
    checkbox_on_states = _get_checkbox_on_states(writer)

    filled = 0
    skipped = 0

    for field_name in raw_fields:
        norm = _normalize_key(field_name)
        if norm in mapping:
            value = mapping[norm]
            ft = field_types.get(field_name, "")

            if ft == "/Btn":
                if _is_truthy(value):
                    value = checkbox_on_states.get(field_name, "/Yes")
                else:
                    value = "/Off"
            else:
                value = str(value)

            for page in writer.pages:
                writer.update_page_form_field_values(
                    page,
                    {field_name: value},
                )
            filled += 1
        else:
            skipped += 1

    with open(output_path, "wb") as out:
        writer.write(out)

    return FillResult(
        output_path=str(output_path),
        fields_filled=filled,
        fields_skipped=skipped,
        fields_total=len(raw_fields),
    )

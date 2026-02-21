# SKPDF — Technical Architecture

## Design Principles

1. **Profile-first** — your CapAuth profile is the single source of truth
2. **Ask only what's missing** — never re-ask what the AI already knows
3. **File immediately** — no PDF left in Downloads, ever
4. **GTD-native** — every document has a place and a status
5. **Modular** — standalone CLI + SKChat plugin + API

---

## System Layers

```
┌─────────────────────────────────────────────────────┐
│ Layer 5: Interface                                    │
│   CLI (Typer) │ SKChat Plugin │ FastAPI │ Web UI      │
├─────────────────────────────────────────────────────┤
│ Layer 4: Orchestrator                                 │
│   FormSession │ QuestionEngine │ ReviewEngine         │
├─────────────────────────────────────────────────────┤
│ Layer 3: Processing                                   │
│   FieldExtractor │ FieldMapper │ AutoFiller │ Writer  │
├─────────────────────────────────────────────────────┤
│ Layer 2: Data                                         │
│   ProfileReader │ TemplateLibrary │ OCREngine         │
├─────────────────────────────────────────────────────┤
│ Layer 1: Storage & Filing                             │
│   GTDFiler │ NextcloudBackend │ GDriveBackend │ Local │
└─────────────────────────────────────────────────────┘
```

---

## Component Details

### Layer 5: Interface

#### CLI (Typer)

```python
import typer
from skpdf.core import FormSession

app = typer.Typer()

@app.command()
def fill(
    pdf_path: Path,
    profile: Optional[Path] = None,
    file_to: Optional[str] = None,
    dry_run: bool = False
):
    """
    Fill a PDF form using your CapAuth profile.

    Args:
        pdf_path: Path to the PDF form.
        profile: CapAuth profile path (default: from config).
        file_to: Filing destination (local, nextcloud, gdrive).
        dry_run: Preview without writing.
    """
    session = FormSession(pdf_path, profile)
    session.extract_fields()
    session.auto_fill()

    if session.missing_fields:
        for field in session.missing_fields:
            value = typer.prompt(f"{field.label}")
            session.set_field(field.id, value)

    if dry_run:
        session.preview()
    else:
        output = session.write()
        if file_to:
            session.file(output, destination=file_to)


@app.command()
def organize(
    path: Path,
    destination: str = "local"
):
    """
    Organize PDFs from a messy folder into GTD structure.

    Scans PDFs, categorizes them, and files to the right place.
    """
    from skpdf.gtd import GTDOrganizer
    organizer = GTDOrganizer(destination)
    organizer.process_folder(path)
```

#### SKChat Plugin

```python
from skchat.plugins import SKChatPlugin, SharedFile, ChatContext

class SKPDFPlugin(SKChatPlugin):
    """SKPDF form-filling plugin for SKChat."""

    name = "skpdf"
    version = "0.1.0"
    triggers = ["application/pdf"]

    async def on_file_received(self, file: SharedFile, ctx: ChatContext):
        session = FormSession(file.local_path, ctx.sender_profile)
        session.extract_fields()
        session.auto_fill()

        if not session.has_fillable_fields:
            return

        filled_count = len(session.filled_fields)
        total_count = len(session.all_fields)

        await ctx.reply(
            f"Got it — {total_count}-field form. "
            f"Auto-filled {filled_count} from your profile."
        )

        if session.missing_fields:
            answers = await ctx.ask_batch(
                [f.to_question() for f in session.missing_fields]
            )
            for field_id, value in answers.items():
                session.set_field(field_id, value)

        output = session.write()
        await ctx.send_file(output, f"{file.stem}-FILLED.pdf")

        filing_result = await session.file(output, destination="nextcloud")
        await ctx.reply(
            f"Filed to {filing_result.path}. "
            f"Status: {filing_result.gtd_status}."
        )
```

#### FastAPI

```python
from fastapi import FastAPI, UploadFile
from skpdf.core import FormSession

app = FastAPI(title="SKPDF API")

@app.post("/fill")
async def fill_form(
    pdf: UploadFile,
    profile_uri: str,
    answers: Optional[dict] = None
):
    """
    Fill a PDF form via API.

    Returns filled PDF and metadata.
    """
    session = FormSession.from_upload(pdf, profile_uri)
    session.extract_fields()
    session.auto_fill()

    if answers:
        for field_id, value in answers.items():
            session.set_field(field_id, value)

    if session.missing_fields:
        return {
            "status": "incomplete",
            "filled": len(session.filled_fields),
            "missing": [f.to_dict() for f in session.missing_fields]
        }

    output = session.write()
    return StreamingResponse(output, media_type="application/pdf")
```

---

### Layer 4: Orchestrator

```python
class FormSession:
    """
    Main orchestrator for a PDF form-filling session.

    Manages the lifecycle: extract → map → fill → ask → write → file.
    """

    def __init__(self, pdf_path: Path, profile: Optional[Path] = None):
        self.pdf_path = pdf_path
        self.profile = ProfileReader(profile)
        self.extractor = FieldExtractor()
        self.mapper = FieldMapper()
        self.filler = AutoFiller(self.profile)
        self.writer = PDFWriter()
        self.fields: list[FormField] = []

    def extract_fields(self):
        """Extract all fillable fields from the PDF."""
        self.fields = self.extractor.extract(self.pdf_path)

        if not self.fields:
            ocr_fields = OCREngine().detect_fields(self.pdf_path)
            self.fields = ocr_fields

    def auto_fill(self):
        """Map fields to profile data and fill what we can."""
        for field in self.fields:
            mapping = self.mapper.map_field(field)
            if mapping:
                value = self.filler.get_value(mapping)
                if value:
                    field.value = value
                    field.filled = True
                    field.source = mapping.profile_path

    @property
    def missing_fields(self) -> list[FormField]:
        return [f for f in self.fields if not f.filled and f.required]

    def write(self) -> Path:
        """Write filled fields back to PDF."""
        return self.writer.fill(self.pdf_path, self.fields)

    async def file(self, output: Path, destination: str) -> FilingResult:
        """File the completed PDF using GTD structure."""
        filer = GTDFiler(destination)
        category = filer.categorize(self.pdf_path, self.fields)
        return await filer.file(output, category)
```

---

### Layer 3: Processing

#### Field Extractor

```python
class FieldExtractor:
    """
    Extract form fields from PDFs.

    Handles AcroForms, XFA, and OCR-detected fields.
    """

    def extract(self, pdf_path: Path) -> list[FormField]:
        """
        Extract fields using the best available method.

        Priority: AcroForm fields → XFA fields → OCR detection.
        """
        with pikepdf.open(pdf_path) as pdf:
            acro_fields = self._extract_acroform(pdf)
            if acro_fields:
                return acro_fields

            xfa_fields = self._extract_xfa(pdf)
            if xfa_fields:
                return xfa_fields

        return self._extract_via_ocr(pdf_path)
```

#### Field Mapper

```python
class FieldMapper:
    """
    Map PDF field labels to CapAuth profile paths.

    Uses a combination of:
    - Exact match dictionary ("Patient Name" → identity.full_name)
    - Fuzzy matching for variations
    - LLM-assisted mapping for ambiguous fields
    """

    FIELD_MAP = {
        "name": "identity.full_name",
        "patient name": "identity.full_name",
        "full name": "identity.full_name",
        "first name": "identity.first_name",
        "last name": "identity.last_name",
        "date of birth": "identity.date_of_birth",
        "dob": "identity.date_of_birth",
        "social security": "identity.ssn_encrypted",
        "ssn": "identity.ssn_encrypted",
        "address": "contact.address.street",
        "city": "contact.address.city",
        "state": "contact.address.state",
        "zip": "contact.address.zip",
        "zip code": "contact.address.zip",
        "phone": "contact.phone",
        "email": "contact.email",
        "insurance provider": "medical.insurance_provider",
        "policy number": "medical.policy_number",
        "group number": "medical.group_number",
        "employer": "financial.employer",
        # ... hundreds more mappings
    }

    def map_field(self, field: FormField) -> Optional[FieldMapping]:
        label = field.label.lower().strip()

        if label in self.FIELD_MAP:
            return FieldMapping(
                field_id=field.id,
                profile_path=self.FIELD_MAP[label],
                confidence=1.0
            )

        fuzzy = self._fuzzy_match(label)
        if fuzzy and fuzzy.confidence > 0.8:
            return fuzzy

        return self._llm_map(field)
```

#### Auto-Filler with Advocate Gate

```python
class AutoFiller:
    """
    Fill fields from CapAuth profile data.

    Sensitive fields require AI advocate approval before filling.
    """

    SENSITIVE_FIELDS = {
        "identity.ssn_encrypted",
        "financial.account_number_encrypted",
        "financial.routing_number",
    }

    def get_value(self, mapping: FieldMapping) -> Optional[str]:
        profile_path = mapping.profile_path

        if profile_path in self.SENSITIVE_FIELDS:
            if not self.advocate.approve_disclosure(profile_path):
                return None
            return self.profile.decrypt_field(profile_path)

        return self.profile.get_field(profile_path)
```

---

### Layer 2: Data

#### Profile Reader

```python
class ProfileReader:
    """
    Read data from CapAuth sovereign profile.

    Handles encrypted fields, nested structures, and PGP decryption.
    """

    def __init__(self, profile_path: Optional[Path] = None):
        self.profile = CapAuthProfile.load(
            profile_path or self._default_profile()
        )

    def get_field(self, dotted_path: str) -> Optional[str]:
        """
        Get a field value by dotted path.

        Example: "contact.address.city" → "Palm Beach"
        """
        parts = dotted_path.split(".")
        value = self.profile.data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return str(value)

    def decrypt_field(self, dotted_path: str) -> Optional[str]:
        """Decrypt a sensitive field using PGP."""
        encrypted = self.get_field(dotted_path)
        if encrypted:
            return self.profile.pgp.decrypt(encrypted)
        return None
```

#### Template Library

```python
class TemplateLibrary:
    """
    Pre-mapped field templates for common forms.

    Templates provide exact field-to-profile mappings,
    bypassing fuzzy matching for 99% accuracy.
    """

    def match(self, pdf_path: Path) -> Optional[FormTemplate]:
        """
        Check if this PDF matches a known template.

        Uses title extraction, page count, and field fingerprinting.
        """
        fingerprint = self._fingerprint(pdf_path)
        return self.templates.get(fingerprint)
```

---

### Layer 1: Storage & Filing

#### GTD Filer

```python
class GTDFiler:
    """
    File PDFs using GTD (Getting Things Done) principles.

    Every PDF gets: categorized, named, metadata'd, and placed.
    """

    CATEGORIES = {
        "medical": ["insurance", "doctor", "hospital", "pharmacy", "health"],
        "financial": ["tax", "bank", "loan", "credit", "investment"],
        "legal": ["contract", "agreement", "court", "attorney", "will"],
        "housing": ["lease", "rent", "mortgage", "utility", "HOA"],
        "vehicle": ["DMV", "registration", "title", "insurance"],
        "government": ["IRS", "SSA", "passport", "visa", "license"],
        "personal": ["school", "employment", "certificate"],
    }

    def categorize(self, pdf_path: Path, fields: list[FormField]) -> str:
        """
        Determine the category for a PDF based on content.

        Analyzes field labels, form title, and extracted text.
        """
        text = self._extract_text(pdf_path)
        field_labels = " ".join(f.label for f in fields)
        combined = f"{text} {field_labels}".lower()

        scores = {}
        for category, keywords in self.CATEGORIES.items():
            scores[category] = sum(
                1 for kw in keywords if kw.lower() in combined
            )

        return max(scores, key=scores.get) if max(scores.values()) > 0 else "personal"

    async def file(
        self,
        pdf_path: Path,
        category: str,
        status: str = "reference"
    ) -> FilingResult:
        """
        File a PDF to the correct GTD location.

        Creates the folder structure if needed, generates the
        standardized filename, and writes the metadata sidecar.
        """
        dest_folder = self._get_folder(category, status)
        filename = self._generate_filename(pdf_path, category)
        dest_path = dest_folder / filename

        await self.backend.write(pdf_path, dest_path)
        await self._write_metadata(dest_path, pdf_path, category, status)

        return FilingResult(
            path=dest_path,
            category=category,
            gtd_status=status,
            metadata_path=dest_path.with_suffix(".pdf.meta.yml")
        )
```

---

## Data Models

```python
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path
from typing import Optional

class FormField(BaseModel):
    """A single field in a PDF form."""
    id: str
    label: str
    field_type: str          # text, checkbox, radio, dropdown, signature, date
    page: int
    required: bool = True
    value: Optional[str] = None
    filled: bool = False
    source: Optional[str] = None  # profile path that filled it
    confidence: float = 0.0

class FieldMapping(BaseModel):
    """Mapping from a PDF field to a profile data path."""
    field_id: str
    profile_path: str        # e.g., "contact.address.city"
    confidence: float

class FilingResult(BaseModel):
    """Result of filing a PDF to storage."""
    path: Path
    category: str
    gtd_status: str          # inbox, action, waiting-for, reference, archive
    metadata_path: Path
    filed_at: datetime
    destinations: list[str]  # ["local", "nextcloud"]

class PDFMetadata(BaseModel):
    """Metadata sidecar for a filed PDF."""
    original_filename: str
    filed_date: datetime
    category: str
    subcategory: Optional[str]
    source: Optional[str]
    status: str
    follow_up_date: Optional[datetime]
    fields_filled: int
    fields_auto: int
    fields_manual: int
    sensitive_fields: list[str]
    filed_by: str
    filed_to: list[str]
    tags: list[str]
```

---

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Field extraction | < 2s | Interactive PDF |
| Field extraction (OCR) | < 10s | Scanned PDF |
| Auto-fill | < 500ms | From cached profile |
| PDF writing | < 1s | Fill + flatten |
| Filing | < 3s | Local + Nextcloud upload |
| Template matching | < 200ms | Fingerprint lookup |
| Total (simple form) | < 5s | Extract → fill → write → file |

---

*Architecture designed by Opus + Lumina for the smilinTux ecosystem.*
*Because paperwork is not a personality trait.* 🐧👑

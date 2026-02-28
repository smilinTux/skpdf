"""
SKPDF Command Line Interface.

Provides `skpdf extract`, `skpdf fill`, and `skpdf file` commands for
PDF form field extraction, auto-filling, and GTD filing.
"""

import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .extractor import extract_fields
from .filler import fill_pdf
from .models import GTDStatus

console = Console()


@click.group()
@click.version_option(version="0.2.0", prog_name="skpdf")
def cli():
    """SKPDF - PDF field extraction and auto-fill.

    Extract form fields from PDFs and fill them from JSON profiles.

    Examples:

        skpdf extract form.pdf

        skpdf fill form.pdf --profile profile.json
    """
    pass


@cli.command()
@click.argument("pdf_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Save output to file")
def extract(pdf_file: str, fmt: str, output: Optional[str]):
    """Extract form fields from a PDF.

    Args:
        pdf_file: Path to the PDF to extract fields from.

    Examples:

        skpdf extract tax_form.pdf

        skpdf extract form.pdf --format json --output fields.json
    """
    try:
        result = extract_fields(pdf_file)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if result.total_fields == 0:
        console.print("[yellow]No form fields found in this PDF.[/yellow]")
        return

    if fmt == "json":
        data = result.model_dump(mode="json")
        text = json.dumps(data, indent=2)
        if output:
            Path(output).write_text(text)
            console.print(f"[green]Fields saved to {output}[/green]")
        else:
            click.echo(text)
    else:
        table = Table(title=f"Fields in {result.filename} ({result.total_fields})")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Value", style="green")
        table.add_column("Required", style="red")

        for field in result.fields:
            table.add_row(
                field.name,
                field.field_type.value,
                str(field.value or ""),
                "Yes" if field.required else "",
            )

        console.print(table)

        if output:
            data = result.model_dump(mode="json")
            Path(output).write_text(json.dumps(data, indent=2))
            console.print(f"\n[green]Also saved to {output}[/green]")


@cli.command()
@click.argument("pdf_file", type=click.Path(exists=True))
@click.option(
    "--profile",
    "-p",
    required=True,
    type=click.Path(exists=True),
    help="JSON profile with field values",
)
@click.option("--output", "-o", type=click.Path(), help="Output PDF path")
@click.option(
    "--file-to",
    multiple=True,
    help="File filled PDF to storage backend(s): local, nextcloud, gdrive, dropbox",
)
@click.option("--category", "-c", help="Filing category (auto-detected if omitted)")
@click.option(
    "--status",
    "-s",
    type=click.Choice([s.value for s in GTDStatus]),
    default="reference",
    help="GTD status for filing",
)
@click.option("--source", help="Document source/issuer")
def fill(
    pdf_file: str,
    profile: str,
    output: Optional[str],
    file_to: tuple[str, ...],
    category: Optional[str],
    status: str,
    source: Optional[str],
):
    """Fill a PDF form from a JSON profile.

    Args:
        pdf_file: Path to the PDF form to fill.

    Examples:

        skpdf fill tax_form.pdf --profile my_info.json

        skpdf fill form.pdf -p profile.json -o filled_form.pdf

        skpdf fill form.pdf -p profile.json --file-to local --file-to nextcloud
    """
    try:
        result = fill_pdf(pdf_file, profile, output)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    console.print(f"[green]Filled PDF saved to {result.output_path}[/green]")
    console.print(
        f"  Fields filled: {result.fields_filled}/{result.fields_total} "
        f"({result.fields_skipped} skipped)"
    )

    if file_to:
        _file_pdf(
            pdf_path=result.output_path,
            backends=list(file_to),
            category=category,
            gtd_status=status,
            source=source,
            fill_stats={
                "fields_filled": result.fields_filled,
                "fields_auto": result.fields_filled,
                "fields_manual": 0,
            },
        )


@cli.command("file")
@click.argument("pdf_file", type=click.Path(exists=True))
@click.option(
    "--to",
    "backends",
    multiple=True,
    default=("local",),
    help="Storage backend(s): local, nextcloud, gdrive, dropbox",
)
@click.option("--category", "-c", help="Filing category (auto-detected if omitted)")
@click.option(
    "--status",
    "-s",
    type=click.Choice([s.value for s in GTDStatus]),
    default="reference",
    help="GTD status",
)
@click.option("--source", help="Document source/issuer")
@click.option("--subcategory", help="Filing subcategory")
@click.option("--tag", multiple=True, help="Additional tags")
def file_cmd(
    pdf_file: str,
    backends: tuple[str, ...],
    category: Optional[str],
    status: str,
    source: Optional[str],
    subcategory: Optional[str],
    tag: tuple[str, ...],
):
    """File a PDF to GTD-organized storage.

    Categorizes the document and files it with a standardized name
    and metadata sidecar.

    Examples:

        skpdf file claim_form.pdf

        skpdf file tax_1099.pdf --to local --to nextcloud --category financial

        skpdf file contract.pdf --status waiting-for --source "Acme Corp"
    """
    _file_pdf(
        pdf_path=pdf_file,
        backends=list(backends),
        category=category,
        gtd_status=status,
        source=source,
        subcategory=subcategory,
        tags=list(tag) if tag else None,
    )


def _file_pdf(
    pdf_path: str,
    backends: list[str],
    category: Optional[str] = None,
    gtd_status: str = "reference",
    source: Optional[str] = None,
    subcategory: Optional[str] = None,
    fill_stats: Optional[dict] = None,
    tags: Optional[list[str]] = None,
) -> None:
    """Internal helper for filing a PDF via GTDFiler."""
    from .gtd_filer import GTDFiler
    from .storage import LocalBackend, get_backend

    path = Path(pdf_path)

    # Extract fields for categorization
    try:
        extraction = extract_fields(str(path))
        fields = extraction.fields
    except Exception:
        fields = None

    # Build backends
    backend_instances = []
    for name in backends:
        try:
            if name == "local":
                backend_instances.append(LocalBackend())
            else:
                console.print(
                    f"[yellow]Backend '{name}' requires configuration. "
                    f"Using local fallback.[/yellow]"
                )
                backend_instances.append(LocalBackend())
        except Exception as e:
            console.print(f"[red]Error initializing {name}:[/red] {e}")

    if not backend_instances:
        backend_instances = [LocalBackend()]

    filer = GTDFiler(backends=backend_instances)

    try:
        result = filer.file(
            pdf_path=path,
            category=category,
            gtd_status=gtd_status,
            source=source,
            subcategory=subcategory,
            fields=fields,
            fill_stats=fill_stats,
            tags=tags,
        )

        console.print(f"\n[green]Filed successfully[/green]")
        console.print(f"  Category: {result.category}")
        console.print(f"  GTD status: {result.gtd_status}")
        console.print(f"  Path: {result.path}")
        console.print(f"  Metadata: {result.metadata_path}")
        for dest in result.destinations:
            console.print(f"  -> {dest}")

    except Exception as e:
        console.print(f"[red]Filing error:[/red] {e}")
        raise SystemExit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()

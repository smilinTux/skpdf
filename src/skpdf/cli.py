"""
SKPDF Command Line Interface.

Provides `skpdf extract` and `skpdf fill` commands for
PDF form field extraction and auto-filling.
"""

import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .extractor import extract_fields
from .filler import fill_pdf

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="skpdf")
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
def fill(pdf_file: str, profile: str, output: Optional[str]):
    """Fill a PDF form from a JSON profile.

    Args:
        pdf_file: Path to the PDF form to fill.

    Examples:

        skpdf fill tax_form.pdf --profile my_info.json

        skpdf fill form.pdf -p profile.json -o filled_form.pdf
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


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()

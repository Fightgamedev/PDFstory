from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PdfError(Exception):
    pass


def extract_pages(pdf_path: Path) -> list[str]:
    if shutil.which("pdftotext") is None:
        raise PdfError("pdftotext is missing. Install Poppler (for example, poppler-utils on Ubuntu).")

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfError("PDF text extraction took too long.") from exc
    except OSError as exc:
        raise PdfError(f"Could not start pdftotext: {exc}") from exc

    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise PdfError(detail or "Could not read this PDF.")

    text = result.stdout.decode("utf-8", errors="replace")
    pages = [page.strip() for page in text.split("\f")]
    while pages and not pages[-1]:
        pages.pop()
    if not pages or not any(pages):
        raise PdfError("No selectable text was found. Scanned PDFs need OCR, which is not in this first version.")
    return pages

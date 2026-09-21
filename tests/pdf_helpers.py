"""Tiny PDF fixtures with embedded text, built without an OCR dependency."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfWriter


def make_text_pdf(pages: list[str]) -> bytes:
    """Build a minimal valid PDF whose page text pypdf can extract."""

    if not pages:
        raise ValueError("At least one page is required")

    objects: dict[int, bytes] = {}
    page_numbers = [4 + (index * 2) for index in range(len(pages))]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{number} 0 R' for number in page_numbers)}] "
        f"/Count {len(pages)} >>"
    ).encode("ascii")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for index, page_text in enumerate(pages):
        page_number = page_numbers[index]
        content_number = page_number + 1
        stream = _text_stream(page_text)
        objects[page_number] = (
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_number} 0 R >>"
        ).encode("ascii")
        objects[content_number] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number in range(1, len(objects) + 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(objects[number])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def make_blank_pdf() -> bytes:
    """Build an image-only-equivalent PDF with no extractable text layer."""

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _text_stream(text: str) -> bytes:
    commands = ["BT", "/F1 11 Tf", "72 720 Td"]
    for index, line in enumerate(text.splitlines() or [text]):
        if index:
            commands.append("0 -15 Td")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1")


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

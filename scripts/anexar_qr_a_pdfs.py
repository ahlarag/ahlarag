#!/usr/bin/env python3
"""Anexa un código QR con el texto de cada hoja a PDFs de formularios."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pdfplumber
import qrcode
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# Capacidad aproximada QR versión 40-L ~2953 bytes; con M menos.
# Estos formularios tienen <600 chars; caben con holgura.
MAX_QR_CHARS = 2000
# QR sintético: ~2.2 cm (~62 pt), pie discreto sin banda grande.
QR_SIZE_MM = 22
MARGIN_BOTTOM_MM = 5
MARGIN_RIGHT_MM = 5
LABEL_GAP_MM = 1.5


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_for_qr(text: str, limit: int = MAX_QR_CHARS) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    # Truncar por caracteres hasta caber en bytes UTF-8
    out = text
    while len(out.encode("utf-8")) > limit - 20 and out:
        out = out[:-50]
    return out.rstrip() + "\n…[truncado]"


def extract_page_text(pdf_path: Path, page_index: int) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        raw = page.extract_text() or ""
        title_hint = pdf_path.stem.replace("_", " ")
        # Normalizar bullets raros
        raw = raw.replace("", "•").replace("\uf0d8", "•")
        cleaned = clean_text(raw)
        if not cleaned:
            cleaned = f"Documento: {title_hint}\n(Sin texto extraíble en esta hoja)"
        else:
            # Asegurar identificación del documento al inicio
            header = f"Documento: {Path(pdf_path).name}\n"
            if not cleaned.upper().startswith("REQUISITOS") and "Documento:" not in cleaned[:40]:
                cleaned = header + cleaned
        return truncate_for_qr(cleaned)


def content_bottom_pt(pdf_path: Path, page_index: int) -> float | None:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words() or []
        if not words:
            return None
        return max(w["bottom"] for w in words)


def make_qr_image(data: str) -> ImageReader:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def build_qr_overlay(
    page_width: float,
    page_height: float,
    qr_img: ImageReader,
    label: str,
    content_bottom: float | None = None,
) -> bytes:
    """Estampa un QR compacto abajo a la derecha, sin expandir el layout."""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))

    qr_size = QR_SIZE_MM * mm
    margin_bottom = MARGIN_BOTTOM_MM * mm
    margin_right = MARGIN_RIGHT_MM * mm
    label_h = 7

    # Siempre al pie inferior derecho: discreto y predecible.
    y_qr = margin_bottom
    x_qr = page_width - margin_right - qr_size

    # Si el contenido llega muy abajo, no taparlo: subir solo lo necesario.
    if content_bottom is not None:
        free_below = page_height - content_bottom
        needed = qr_size + margin_bottom + label_h + LABEL_GAP_MM * mm
        if free_below < needed:
            # Solapa el margen inferior del formulario; sigue siendo sintético.
            y_qr = max(2 * mm, margin_bottom)

    c.setFont("Helvetica", 5.5)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawRightString(x_qr + qr_size, y_qr + qr_size + LABEL_GAP_MM * mm, label)

    c.drawImage(qr_img, x_qr, y_qr, width=qr_size, height=qr_size, mask="auto")

    c.save()
    packet.seek(0)
    return packet.read()


def process_pdf(src: Path, dst: Path) -> dict:
    reader = PdfReader(str(src))
    writer = PdfWriter()
    payloads: list[str] = []

    for i, page in enumerate(reader.pages):
        text = extract_page_text(src, i)
        payloads.append(text)
        qr_img = make_qr_image(text)
        bottom = content_bottom_pt(src, i)

        box = page.mediabox
        w = float(box.width)
        h = float(box.height)

        overlay_bytes = build_qr_overlay(
            w,
            h,
            qr_img,
            "QR",
            bottom,
        )
        overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
        page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        writer.write(f)

    return {
        "src": str(src),
        "dst": str(dst),
        "pages": len(reader.pages),
        "qr_chars": [len(p) for p in payloads],
        "qr_preview": payloads[0][:120] if payloads else "",
    }


JOBS = [
    (
        "Solicitud_De_Servicio_Persona_Natural_1b2c.pdf",
        "Solicitud_De_Servicio_Persona_Natural_con_QR.pdf",
    ),
    (
        "Solicitud_De_Servicio_Juridico_99ea.pdf",
        "Solicitud_De_Servicio_Juridico_con_QR.pdf",
    ),
    (
        "Cambio_De_Titularidad_Juridico_a089.pdf",
        "Cambio_De_Titularidad_Juridico_con_QR.pdf",
    ),
    (
        "Cambio_De_Titular_Persona_Natural_c858.pdf",
        "Cambio_De_Titular_Persona_Natural_con_QR.pdf",
    ),
    (
        "Aumento_De_Potencia_daec.pdf",
        "Aumento_De_Potencia_con_QR.pdf",
    ),
]


def main() -> None:
    import zipfile

    uploads = Path("/home/ubuntu/.cursor/projects/workspace/uploads")
    out_dirs = [
        Path("/workspace/dist/pdfs_con_qr"),
        Path("/opt/cursor/artifacts/pdfs_con_qr"),
    ]
    for out in out_dirs:
        out.mkdir(parents=True, exist_ok=True)

    results = []
    pdf_names: list[str] = []
    for src_name, dst_name in JOBS:
        src = uploads / src_name
        if not src.exists():
            raise FileNotFoundError(src)
        primary = out_dirs[0] / dst_name
        info = process_pdf(src, primary)
        # Copia a artifacts
        artifact = out_dirs[1] / dst_name
        artifact.write_bytes(primary.read_bytes())
        info["artifact"] = str(artifact)
        results.append(info)
        pdf_names.append(dst_name)
        print(f"OK {dst_name} pages={info['pages']} qr_chars={info['qr_chars']}")

    zip_name = "CORPOELEC_PDFs_con_QR.zip"
    for out in out_dirs:
        zip_path = out / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in pdf_names:
                zf.write(out_dirs[0] / name, arcname=name)
        print(f"ZIP: {zip_path}")

    # Resumen de payloads
    summary = Path("/workspace/dist/pdfs_con_qr/RESUMEN_QR.txt")
    lines = []
    for r in results:
        lines.append(f"=== {Path(r['dst']).name} ===")
        lines.append(f"Fuente: {r['src']}")
        lines.append(f"Caracteres en QR: {r['qr_chars']}")
        text = extract_page_text(Path(r["src"]), 0)
        lines.append(text)
        lines.append("")
    summary.write_text("\n".join(lines), encoding="utf-8")
    print(f"Resumen: {summary}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Genera PDFs de requisitos CORPOELEC con estilo moderno y QR en tarjeta."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# Paleta (referencia visual)
BLUE = (0.10, 0.22, 0.45)  # #1A386F approx
RED = (0.78, 0.12, 0.16)  # #C71F29 approx
TEXT = (0.18, 0.22, 0.28)
CAPTION = (0.45, 0.48, 0.52)
FOOTER = (0.62, 0.64, 0.68)
BOX_BG = (0.93, 0.95, 0.97)  # gris-azul claro
INFO_BG = (1.0, 0.97, 0.88)
INFO_BORDER = (0.92, 0.82, 0.45)
INFO_ICON = (0.90, 0.72, 0.12)
WHITE = (1, 1, 1)
SHADOW = (0.78, 0.80, 0.84)

PAGE_W, PAGE_H = A4
MARGIN_X = 28 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X


@dataclass
class DocSpec:
    src_name: str
    dst_name: str
    title: str
    subtitle: str | None
    items: list[str]
    info: str | None  # caja amarilla (última nota condicional)


DOCS: list[DocSpec] = [
    DocSpec(
        src_name="Solicitud_De_Servicio_Persona_Natural_1b2c.pdf",
        dst_name="Solicitud_De_Servicio_Persona_Natural_con_QR.pdf",
        title="REQUISITOS SOLICITUD DE SERVICIO",
        subtitle="PERSONA NATURAL",
        items=[
            "Copia del documento de propiedad notariado o registrado.",
            "Fotocopia de la Cédula de Identidad del Propietario.",
            "Rif actualizado",
            "Carga (descripción de electrodomésticos)",
            "Croquis de Ubicación",
            "Copia de una Factura de Electricidad del vecino más cercano.",
        ],
        info="En caso de NO ser el Propietario traer Autorización y Copia de CI del autorizado.",
    ),
    DocSpec(
        src_name="Solicitud_De_Servicio_Juridico_99ea.pdf",
        dst_name="Solicitud_De_Servicio_Juridico_con_QR.pdf",
        title="REQUISITOS SOLICITUD DE SERVICIO",
        subtitle="PERSONA JURIDICA",
        items=[
            "Copia del documento de propiedad notariado o registrado.",
            "Copia del Rif de la empresa",
            "Copia del registro mercantil",
            "Acta de asamblea o junta directiva vigente",
            "Copia de la cédula de identidad del presidente o Rep. legal de la empresa.",
            "Carga (descripción de electrodomésticos)",
            "Croquis de Ubicación",
            "Copia de una Factura de Electricidad del vecino más cercano.",
        ],
        info="En caso de NO ser el Propietario traer Autorización y Copia de CI del autorizado.",
    ),
    DocSpec(
        src_name="Cambio_De_Titularidad_Juridico_a089.pdf",
        dst_name="Cambio_De_Titularidad_Juridico_con_QR.pdf",
        title="REQUISITOS",
        subtitle="CAMBIO DE TITULAR PERSONA JURIDICA",
        items=[
            "Copia del Documento de Propiedad Registrado o Notariado o Contrato de Arrendamiento.",
            "Copia del R.I.F de la empresa",
            "Copia del Registro Mercantil",
            "Acta de Asamblea o Junta Directiva Vigente.",
            "Copia de la Cédula de Identidad del presidente o Rep. Legal de la Empresa.",
            "Copia de Factura de Electricidad",
            "Si es Inquilino debe pagar depósito en Garantía. (El monto depende de la tarifa).",
        ],
        info="En caso de NO ser el Rep. Legal traer Autorización y Copia de CI del autorizado.",
    ),
    DocSpec(
        src_name="Cambio_De_Titular_Persona_Natural_c858.pdf",
        dst_name="Cambio_De_Titular_Persona_Natural_con_QR.pdf",
        title="REQUISITOS CAMBIO DE TITULARIDAD",
        subtitle="PERSONA NATURAL",
        items=[
            "Copia del Documento de Propiedad Notariado o Registrado",
            "Fotocopia de la Cédula de Identidad del Propietario.",
            "Copia de la última Factura de Electricidad pagada.",
            "Rif.",
        ],
        info="En caso de NO ser el Propietario traer Autorización y Copia de CI del autorizado.",
    ),
    DocSpec(
        src_name="Aumento_De_Potencia_daec.pdf",
        dst_name="Aumento_De_Potencia_con_QR.pdf",
        title="REQUISITOS AUMENTO DE POTENCIA",
        subtitle=None,
        items=[
            "Fotocopia de la Cédula de Identidad del Propietario.",
            "Croquis de Ubicación.",
            "Copia de la última Factura de Electricidad pagada.",
            "Carga (Descripción de los electrodomésticos)",
            "Rif.",
        ],
        info="En caso de NO ser el Propietario traer Autorización y Copia de CI del autorizado.",
    ),
]


def qr_payload(doc: DocSpec) -> str:
    lines = [doc.title]
    if doc.subtitle:
        lines.append(doc.subtitle)
    lines.append("")
    for item in doc.items:
        lines.append(f"• {item}")
    if doc.info:
        lines.append(f"• {doc.info}")
    return "\n".join(lines)


def make_qr_image(data: str) -> ImageReader:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _set_rgb(c: canvas.Canvas, rgb: tuple[float, float, float], fill: bool = True) -> None:
    if fill:
        c.setFillColorRGB(*rgb)
    else:
        c.setStrokeColorRGB(*rgb)


def draw_checkmark_bullet(c: canvas.Canvas, cx: float, cy: float, r: float = 5.2) -> None:
    """Círculo rojo con check blanco."""
    _set_rgb(c, RED)
    c.circle(cx, cy, r, stroke=0, fill=1)
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(1.35)
    c.setLineCap(1)
    c.setLineJoin(1)
    # Check mark
    c.line(cx - 2.2, cy - 0.2, cx - 0.5, cy - 2.0)
    c.line(cx - 0.5, cy - 2.0, cx + 2.4, cy + 2.0)


def wrap_text(c: canvas.Canvas, text: str, font: str, size: float, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = w if not cur else f"{cur} {w}"
        if c.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def draw_info_box(
    c: canvas.Canvas, x: float, y_top: float, width: float, text: str
) -> float:
    """Caja amarilla informativa. Retorna y inferior."""
    pad_x = 10
    pad_y = 9
    icon_r = 7
    text_x = x + pad_x + icon_r * 2 + 8
    text_w = width - (text_x - x) - pad_x
    font, size = "Helvetica", 9.5
    bold_parts = ("Autorización", "Copia de CI", "Rep. Legal")

    # Resaltar palabras clave en negrita al medir/dibujar
    lines = wrap_text(c, text, font, size, text_w)
    line_h = 13
    box_h = pad_y * 2 + max(len(lines) * line_h, icon_r * 2 + 4)
    y = y_top - box_h

    _set_rgb(c, INFO_BG)
    c.setStrokeColorRGB(*INFO_BORDER)
    c.setLineWidth(1.0)
    c.roundRect(x, y, width, box_h, 6, stroke=1, fill=1)

    # Icono info
    ix = x + pad_x + icon_r
    iy = y + box_h / 2
    _set_rgb(c, INFO_ICON)
    c.circle(ix, iy, icon_r, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(ix, iy - 3.2, "i")

    # Texto con negritas simples
    ty = y + box_h - pad_y - 10
    for line in lines:
        draw_rich_line(c, text_x, ty, line, size, bold_parts)
        ty -= line_h
    return y


def draw_rich_line(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    size: float,
    bold_keywords: tuple[str, ...],
) -> None:
    """Dibuja una línea resaltando palabras clave en bold."""
    # Tokenizar preservando espacios
    remaining = text
    cursor = x
    while remaining:
        # Buscar próxima keyword
        next_idx = len(remaining)
        next_kw = None
        for kw in bold_keywords:
            idx = remaining.find(kw)
            if idx != -1 and idx < next_idx:
                next_idx = idx
                next_kw = kw
        if next_kw is None:
            c.setFillColorRGB(*TEXT)
            c.setFont("Helvetica", size)
            c.drawString(cursor, y, remaining)
            break
        if next_idx > 0:
            prefix = remaining[:next_idx]
            c.setFillColorRGB(*TEXT)
            c.setFont("Helvetica", size)
            c.drawString(cursor, y, prefix)
            cursor += c.stringWidth(prefix, "Helvetica", size)
        c.setFillColorRGB(*TEXT)
        c.setFont("Helvetica-Bold", size)
        c.drawString(cursor, y, next_kw)
        cursor += c.stringWidth(next_kw, "Helvetica-Bold", size)
        remaining = remaining[next_idx + len(next_kw) :]


def draw_requirements_box(
    c: canvas.Canvas, doc: DocSpec, y_top: float
) -> float:
    x = MARGIN_X
    width = CONTENT_W
    pad_x = 14
    pad_top = 16
    pad_bottom = 14
    bullet_x = x + pad_x + 6
    text_x = bullet_x + 14
    text_w = width - (text_x - x) - pad_x
    font, size = "Helvetica", 10.5
    line_h = 14.5
    item_gap = 8

    # Medir altura
    item_heights: list[float] = []
    for item in doc.items:
        lines = wrap_text(c, item, font, size, text_w)
        item_heights.append(max(len(lines) * line_h, 12) + item_gap)

    info_h = 0.0
    if doc.info:
        # Estimar altura info
        info_text_w = width - 2 * 12 - 14 - 16
        info_lines = wrap_text(c, doc.info, "Helvetica", 9.5, info_text_w)
        info_h = 18 + max(len(info_lines) * 13, 18) + 10

    content_h = sum(item_heights) - item_gap + pad_top + pad_bottom + info_h
    y = y_top - content_h

    _set_rgb(c, BOX_BG)
    c.setStrokeColorRGB(0.88, 0.90, 0.93)
    c.setLineWidth(0.6)
    c.roundRect(x, y, width, content_h, 10, stroke=1, fill=1)

    cy = y_top - pad_top - 4
    for item, ih in zip(doc.items, item_heights):
        lines = wrap_text(c, item, font, size, text_w)
        first_mid = cy - 3
        draw_checkmark_bullet(c, bullet_x, first_mid + 2.5)
        c.setFillColorRGB(*TEXT)
        c.setFont(font, size)
        ty = cy - 2
        for ln in lines:
            c.drawString(text_x, ty, ln)
            ty -= line_h
        cy -= ih

    if doc.info:
        draw_info_box(c, x + 12, y + pad_bottom + info_h - 4, width - 24, doc.info)

    return y


def draw_l_bracket(
    c: canvas.Canvas, x: float, y: float, corner: str, length: float = 9, thick: float = 2.0
) -> None:
    """Esquinas L rojas estilo mira de escaneo. corner: tl/tr/bl/br."""
    c.setStrokeColorRGB(*RED)
    c.setLineWidth(thick)
    c.setLineCap(1)
    if corner == "tl":
        c.line(x, y - length, x, y)
        c.line(x, y, x + length, y)
    elif corner == "tr":
        c.line(x, y - length, x, y)
        c.line(x - length, y, x, y)
    elif corner == "bl":
        c.line(x, y, x, y + length)
        c.line(x, y, x + length, y)
    elif corner == "br":
        c.line(x, y, x, y + length)
        c.line(x - length, y, x, y)


def draw_qr_card(c: canvas.Canvas, qr_img: ImageReader, y_top: float) -> float:
    """Bloque QR centrado: caption, tarjeta con sombra, marco azul, L rojas, footer."""
    caption = "ESCANEE PARA VER LOS REQUISITOS"
    footer = "Versión digital actualizada"

    qr_size = 48 * mm
    border = 2.2
    card_pad = 10
    card_size = qr_size + 2 * card_pad + 2 * border
    card_radius = 8

    # Caption
    c.setFillColorRGB(*CAPTION)
    c.setFont("Helvetica", 9.5)
    cap_y = y_top - 4
    c.drawCentredString(PAGE_W / 2, cap_y, caption)

    # Posición tarjeta
    gap = 12
    card_top = cap_y - gap
    card_y = card_top - card_size
    card_x = (PAGE_W - card_size) / 2

    # Sombra suave (capas)
    for i, offset in enumerate((3.5, 2.5, 1.5)):
        alpha_rgb = (
            SHADOW[0] + 0.04 * i,
            SHADOW[1] + 0.04 * i,
            SHADOW[2] + 0.04 * i,
        )
        _set_rgb(c, alpha_rgb)
        c.roundRect(
            card_x + offset,
            card_y - offset,
            card_size,
            card_size,
            card_radius,
            stroke=0,
            fill=1,
        )

    # Tarjeta blanca
    _set_rgb(c, WHITE)
    c.setStrokeColorRGB(0.90, 0.91, 0.93)
    c.setLineWidth(0.5)
    c.roundRect(card_x, card_y, card_size, card_size, card_radius, stroke=1, fill=1)

    # Marco azul + QR
    frame_x = card_x + card_pad
    frame_y = card_y + card_pad
    frame_s = qr_size + 2 * border
    c.setStrokeColorRGB(*BLUE)
    c.setLineWidth(1.4)
    c.setFillColorRGB(1, 1, 1)
    c.rect(frame_x, frame_y, frame_s, frame_s, stroke=1, fill=1)

    qr_x = frame_x + border
    qr_y = frame_y + border
    c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")

    # Brackets rojos en esquinas del marco
    inset = 1.0
    draw_l_bracket(c, frame_x + inset, frame_y + frame_s - inset, "tl")
    draw_l_bracket(c, frame_x + frame_s - inset, frame_y + frame_s - inset, "tr")
    draw_l_bracket(c, frame_x + inset, frame_y + inset, "bl")
    draw_l_bracket(c, frame_x + frame_s - inset, frame_y + inset, "br")

    # Footer
    foot_y = card_y - 16
    c.setFillColorRGB(*FOOTER)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(PAGE_W / 2, foot_y, footer)
    return foot_y


def build_pdf(doc: DocSpec, dst: Path) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    payload = qr_payload(doc)
    qr_img = make_qr_image(payload)

    c = canvas.Canvas(str(dst), pagesize=A4)

    # Fondo blanco limpio
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # Header
    y = PAGE_H - 32 * mm
    c.setFillColorRGB(*BLUE)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(PAGE_W / 2, y, doc.title)

    y -= 18
    if doc.subtitle:
        c.setFillColorRGB(*RED)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(PAGE_W / 2, y, doc.subtitle)
        y -= 10
        # Subrayado rojo corto
        c.setStrokeColorRGB(*RED)
        c.setLineWidth(2.4)
        line_w = 42
        c.line(PAGE_W / 2 - line_w / 2, y, PAGE_W / 2 + line_w / 2, y)
        y -= 18
    else:
        y -= 8
        c.setStrokeColorRGB(*RED)
        c.setLineWidth(2.4)
        line_w = 42
        c.line(PAGE_W / 2 - line_w / 2, y, PAGE_W / 2 + line_w / 2, y)
        y -= 18

    box_bottom = draw_requirements_box(c, doc, y)

    # QR con generoso espacio
    qr_top = box_bottom - 28
    draw_qr_card(c, qr_img, qr_top)

    c.save()
    return {
        "dst": str(dst),
        "qr_chars": len(payload),
        "payload_preview": payload[:160],
    }


def main() -> None:
    out_dirs = [
        Path("/workspace/dist/pdfs_con_qr"),
        Path("/opt/cursor/artifacts/pdfs_con_qr"),
    ]
    for out in out_dirs:
        out.mkdir(parents=True, exist_ok=True)

    results = []
    pdf_names: list[str] = []
    for doc in DOCS:
        primary = out_dirs[0] / doc.dst_name
        info = build_pdf(doc, primary)
        artifact = out_dirs[1] / doc.dst_name
        artifact.write_bytes(primary.read_bytes())
        info["artifact"] = str(artifact)
        info["src"] = doc.src_name
        results.append(info)
        pdf_names.append(doc.dst_name)
        print(f"OK {doc.dst_name} qr_chars={info['qr_chars']}")

    zip_name = "CORPOELEC_PDFs_con_QR.zip"
    for out in out_dirs:
        zip_path = out / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in pdf_names:
                zf.write(out_dirs[0] / name, arcname=name)
        print(f"ZIP: {zip_path}")

    summary = Path("/workspace/dist/pdfs_con_qr/RESUMEN_QR.txt")
    lines: list[str] = []
    for doc, r in zip(DOCS, results):
        lines.append(f"=== {doc.dst_name} ===")
        lines.append(f"Fuente: {doc.src_name}")
        lines.append(f"Caracteres en QR: {r['qr_chars']}")
        lines.append(qr_payload(doc))
        lines.append("")
    summary.write_text("\n".join(lines), encoding="utf-8")
    (out_dirs[1] / "RESUMEN_QR.txt").write_text(summary.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Resumen: {summary}")


if __name__ == "__main__":
    main()

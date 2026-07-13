from __future__ import annotations

from pathlib import Path
from typing import Optional, TypedDict, NotRequired, cast

import fitz  # PyMuPDF
import re
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image
import io
import sys
import pytesseract

# Config Tesseract (Windows)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ----------------------------
# Tipos
# ----------------------------
class FacturaResult(TypedDict):
    tipo: str
    fecha_emision: NotRequired[str]
    fecha_vencimiento: NotRequired[str]
    numero: NotRequired[str]
    monto: NotRequired[str]
    cuit: NotRequired[str]


# ----------------------------
# Helpers: número de factura
# ----------------------------
def normalizar_numero_factura(pv: str, numero_crudo: str) -> str:
    """
    Devuelve: PPPPP-NNNNNNNN
    - PV a 5 dígitos con ceros a la izquierda
    - Número: SIEMPRE últimos 8 dígitos (descarta ceros extra)
    """
    pv5 = re.sub(r"\D", "", pv).zfill(5)
    num = re.sub(r"\D", "", numero_crudo)
    num8 = num[-8:].zfill(8)
    return f"{pv5}-{num8}"


def extraer_numero_factura_auto(texto: str) -> Optional[str]:
    """
    Detecta PV y número de factura desde texto.
    Devuelve PPPPP-NNNNNNNN o None.
    """
    # 1) Formatos típicos: "Nº 0261-000204905", "N°", "Nro", "No", "Número"
    patrones = [
        r"\bN[º°o]?\s*[:\-]?\s*0*(\d{1,5})\s*-\s*0*(\d{6,})\b",
        r"\bNro\.?\s*[:\-]?\s*0*(\d{1,5})\s*-\s*0*(\d{6,})\b",
        r"\bNo\.?\s*[:\-]?\s*0*(\d{1,5})\s*-\s*0*(\d{6,})\b",
        r"\bNúm(?:ero)?\.?\s*[:\-]?\s*0*(\d{1,5})\s*-\s*0*(\d{6,})\b",
        r"\bFactura\s+N[º°o]?\s*[:\-]?\s*0*(\d{1,5})\s*-\s*0*(\d{6,})\b",
    ]
    for pat in patrones:
        m = re.search(pat, texto, flags=re.IGNORECASE)
        if m:
            return normalizar_numero_factura(m.group(1), m.group(2))

    # 2) Estilo AFIP: "Punto de Venta: XXXX ... Comp. Nro: YYYY"
    m2 = re.search(
        r"Punto\s+de\s+Venta\s*[:\-]?\s*0*(\d{1,5}).*?Comp\.?\s*Nro\.?\s*[:\-]?\s*0*(\d+)",
        texto,
        flags=re.IGNORECASE | re.DOTALL
    )
    if m2:
        return normalizar_numero_factura(m2.group(1), m2.group(2))

    return None


# ----------------------------
# Extractores por tipo
# ----------------------------
def extraer_datos_tipo1(texto: str) -> FacturaResult:
    """Factura del colegio (arancel/variable/reinscripción, etc.)"""
    fecha = re.search(r"Fecha:\s*(\d{2}/\d{2}/\d{4})", texto)

    numero = extraer_numero_factura_auto(texto) or "No encontrado"

    vto = re.search(r"Vto:\s*(\d{2}/\d{2}/\d{4}).*?\$ ?([\d\.,]+)", texto, flags=re.DOTALL)
    monto = vto.group(2).replace(".", "").replace(",", "") if vto else "No encontrado"

    cuit_match = re.search(r"CUIT:\s*(\d{2})-(\d{8})-(\d{1})", texto)
    cuit = "".join(cuit_match.groups()) if cuit_match else "No encontrado"

    return {
        "tipo": "Factura Colegio",
        "fecha_emision": fecha.group(1) if fecha else "No encontrada",
        "numero": numero,
        "monto": monto,
        "cuit": cuit,
    }


def extraer_datos_tipo2(texto: str) -> FacturaResult:
    """Factura de luz (tipo 2)"""
    lsp = re.search(r"LSP B (\d{4})-(\d+)", texto)
    total = re.search(r"TOTAL A PAGAR \(1° vencimiento\)\s*\$ ?([\d\.,]+)", texto)
    fecha = re.search(r"Capital Federal\s+(\d{2}/\d{2}/\d{4})", texto)

    nro = f"{lsp.group(1).zfill(5)}-{lsp.group(2)}" if lsp else "No encontrada"
    monto = total.group(1).replace(".", "").replace(",", "") if total else "No encontrado"
    cuit = "30655116512"

    return {
        "tipo": "Factura Luz",
        "fecha_emision": fecha.group(1) if fecha else "No encontrada",
        "numero": nro,
        "monto": monto,
        "cuit": cuit,
    }


def extraer_datos_tipo3(doc: fitz.Document) -> FacturaResult:
    """
    Factura del jardín (tipo 3) con OCR por recortes.
    Depurado para Pylance: get_text("text") + cast(str, ...).
    """
    texto: str = ""
    pagina_objetivo: Optional[fitz.Page] = None

    # 1) Buscar página con "original" (case-insensitive)
    for p_any in doc:
        pagina = cast(fitz.Page, p_any)
        t = cast(str, pagina.get_text("text"))
        if re.search(r"\boriginal\b", t, flags=re.IGNORECASE):
            texto = t
            pagina_objetivo = pagina
            break

    # 2) Fallback: buscar por marcador del jardín
    if pagina_objetivo is None:
        for p_any in doc:
            pagina = cast(fitz.Page, p_any)
            t = cast(str, pagina.get_text("text"))
            if "RECREANDO INFANCIAS" in t:
                texto = t
                pagina_objetivo = pagina
                break

    # 3) Fallback final
    if pagina_objetivo is None:
        if len(doc) == 0:
            raise ValueError("PDF vacío: no hay páginas para procesar (tipo 3).")
        pagina_objetivo = cast(fitz.Page, doc[0])
        texto = cast(str, pagina_objetivo.get_text("text"))

    fechas = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", texto)
    fecha = fechas[0] if fechas else "No encontrada"

    numero = extraer_numero_factura_auto(texto) or "No encontrada"

    # Render a imagen
    pix = pagina_objetivo.get_pixmap(dpi=300)
    img_bytes = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_bytes))

    # OCR Monto
    crop_box_monto = (2200, 1170, 2500, 1220)
    monto = pytesseract.image_to_string(
        img.crop(crop_box_monto),
        config="--psm 6 -c tessedit_char_whitelist=0123456789,."
    ).strip().replace(".", "").replace(",", "")

    # OCR CUIT
    crop_box_cuit = (1320, 540, 1820, 590)
    cuit_ocr = pytesseract.image_to_string(
        img.crop(crop_box_cuit),
        config="--psm 6 -c tessedit_char_whitelist=0123456789"
    ).strip()

    return {
        "tipo": "Factura Jardin",
        "fecha_emision": fecha,
        "numero": numero,
        "monto": monto if monto else "No encontrado",
        "cuit": cuit_ocr if cuit_ocr else "No encontrado",
    }


def extraer_datos_tipo4(texto: str) -> FacturaResult:
    """Factura de instituto de inglés (tipo 4)"""
    numero = extraer_numero_factura_auto(texto) or "No encontrado"

    fecha = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
    fecha_emision = fecha.group(1) if fecha else "No encontrada"

    imp_total = re.search(r"Importe Total:.*?\n([\d\.,]+)", texto)
    if imp_total:
        monto = imp_total.group(1).replace(".", "").replace(",", ".")
    else:
        importes = re.findall(r"(\d{4,}\.\d{2})", texto)
        monto = importes[-1] if importes else "No encontrado"

    cuit_match = re.search(r"CUIT:\s*(\d{2})-(\d{8})-(\d{1})", texto)
    cuit = "".join(cuit_match.groups()) if cuit_match else "No encontrado"

    return {
        "tipo": "Factura Ingles",
        "fecha_emision": fecha_emision,
        "numero": numero,
        "monto": monto,
        "cuit": cuit,
    }


def extraer_datos_tipo5(doc: fitz.Document) -> FacturaResult:
    """Factura Telecom (tipo 5) SOLO página 2."""
    if len(doc) < 2:
        raise ValueError("Factura Telecom: esperaba al menos 2 páginas y el PDF tiene menos.")

    pagina2 = cast(fitz.Page, doc[1])
    texto = cast(str, pagina2.get_text("text"))

    match_fecha = re.search(r"Fecha de Emisi[oó]n\s*:?\s*(\d{2}/\d{2}/\d{4})", texto)
    fecha_emision = match_fecha.group(1) if match_fecha else "No encontrada"

    match_vto = re.search(r"Fecha de Vencimiento\s*:?\s*(\d{2}/\d{2}/\d{4})", texto)
    fecha_vencimiento = match_vto.group(1) if match_vto else "No encontrada"

    numero_factura = extraer_numero_factura_auto(texto) or "No encontrado"

    match_monto = re.search(r"TOTAL DE SERVICIOS DEL MES\s*\$ ?([\d\.]+,\d{2})", texto)
    if match_monto:
        monto = match_monto.group(1).replace(".", "")
    else:
        any_m = re.search(r"\$ ?([\d\.]+,\d{2})", texto)
        monto = any_m.group(1).replace(".", "") if any_m else "No encontrado"

    match_cuit = re.search(r"C\.?U\.?I\.?T\.?:?\s*([\d-]+)", texto)
    cuit = match_cuit.group(1).replace("-", "") if match_cuit else "No encontrado"

    return {
        "tipo": "Factura Telecom",
        "fecha_emision": fecha_emision,
        "fecha_vencimiento": fecha_vencimiento,
        "numero": numero_factura,
        "monto": monto,
        "cuit": cuit,
    }


# ----------------------------
# Identificación de tipo
# ----------------------------
def identificar_tipo(texto: str) -> int:
    t = texto.lower()

    # Tipo 1: Colegio (incluye reinscripción)
    if ("factura arancel" in t) or ("factura variable" in t) or ("factura reinscripci" in t) or ("colegio y oratorio san francisco de" in t):
        return 1

    # Tipo 2: Luz
    if "liquidación de servicios públicos" in t:
        return 2

    # Tipo 3: Jardín
    if "recreando infancias" in t:
        return 3

    # Tipo 4: Inglés
    if ("factura contado" in t) and ("sede central" in t):
        return 4

    # Tipo 5: Telecom
    if ("telecom argentina" in t) and ("total de servicios del mes" in t):
        return 5

    return 0


# ----------------------------
# Procesamiento
# ----------------------------
def procesar_factura(path: Path) -> Optional[FacturaResult]:
    doc: Optional[fitz.Document] = None
    try:
        doc = fitz.open(path)
        # Depurado: get_text("text") para que sea str seguro
        texto_completo = "\n".join(
            cast(str, cast(fitz.Page, p).get_text("text"))
            for p in doc
        )

        tipo = identificar_tipo(texto_completo)

        if tipo == 1:
            return extraer_datos_tipo1(texto_completo)
        if tipo == 2:
            return extraer_datos_tipo2(texto_completo)
        if tipo == 3:
            return extraer_datos_tipo3(doc)
        if tipo == 4:
            return extraer_datos_tipo4(texto_completo)
        if tipo == 5:
            return extraer_datos_tipo5(doc)

        return None

    except Exception as e:
        print(f"[ERROR] {path.name}: {e}")
        return None

    finally:
        if doc is not None:
            doc.close()


def guardar_resultados_por_tipo(resultados: list[FacturaResult]) -> None:
    tipos: dict[str, list[FacturaResult]] = {}

    for r in resultados:
        tipo_key = r["tipo"].lower().replace(" ", "_")
        tipos.setdefault(tipo_key, []).append(r)

    for tipo_key, registros in tipos.items():
        nombre_archivo = f"facturas_{tipo_key}.txt"
        with open(nombre_archivo, "w", encoding="utf-8") as f:
            for r in registros:
                f.write(f"Tipo: {r.get('tipo', 'No encontrado')}\n")
                f.write(f"Fecha de emisión: {r.get('fecha_emision', 'No encontrada')}\n")
                if "fecha_vencimiento" in r:
                    f.write(f"Fecha de vencimiento: {r['fecha_vencimiento']}\n")
                f.write(f"Número de factura: {r.get('numero', 'No encontrado')}\n")
                f.write(f"Monto: ${r.get('monto', 'No encontrado')}\n")
                f.write(f"CUIT: {r.get('cuit', 'No encontrado')}\n")
                f.write("-" * 40 + "\n")


def seleccionar_carpeta_y_ejecutar() -> None:
    carpeta = filedialog.askdirectory(title="Seleccioná la carpeta con los PDFs")
    if not carpeta:
        return

    archivos = list(Path(carpeta).glob("*.pdf"))

    resultados: list[FacturaResult] = []
    for pdf in archivos:
        r = procesar_factura(pdf)
        if r is not None:
            resultados.append(r)

    if not resultados:
        messagebox.showwarning("Sin resultados", "No pude extraer datos de ningún PDF en esa carpeta.")
        return

    guardar_resultados_por_tipo(resultados)
    messagebox.showinfo("¡Listo!", "Extracción completada.\nRevisá los archivos por tipo de factura.")
    ventana.destroy()
    sys.exit()


# ----------------------------
# GUI
# ----------------------------
ventana = tk.Tk()
ventana.title("Extractor de Facturas PDF")
ventana.geometry("420x200")

label = tk.Label(ventana, text="Extrae fecha, número y monto de facturas", font=("Arial", 12))
label.pack(pady=20)

boton = tk.Button(
    ventana,
    text="Seleccionar carpeta y procesar",
    command=seleccionar_carpeta_y_ejecutar,
    font=("Arial", 12)
)
boton.pack(pady=10)

ventana.mainloop()

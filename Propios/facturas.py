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


# ----------------------------
# Configuración de Tesseract
# ----------------------------
# Modificar esta ruta si Tesseract está instalado en otra ubicación.
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# ----------------------------
# Tipos
# ----------------------------
class FacturaResult(TypedDict):
    tipo: str
    nombre: NotRequired[str]
    fecha_emision: NotRequired[str]
    fecha_vencimiento: NotRequired[str]
    numero: NotRequired[str]
    monto: NotRequired[str]
    cuit: NotRequired[str]


# ----------------------------
# Helpers: número de factura
# ----------------------------
def normalizar_numero_factura(
    punto_venta: str,
    numero_crudo: str
) -> str:
    """
    Normaliza el número de factura al formato:

        PPPPP-NNNNNNNNN

    Ejemplo:
        2213-000206069
        02213-000206069

    - Punto de venta: 5 dígitos.
    - Número de comprobante: 9 dígitos.
    """
    pv_limpio = re.sub(r"\D", "", punto_venta)
    numero_limpio = re.sub(r"\D", "", numero_crudo)

    pv5 = pv_limpio.zfill(5)

    # Conserva siempre los últimos 9 dígitos.
    numero9 = numero_limpio[-9:].zfill(9)

    return f"{pv5}-{numero9}"


def extraer_numero_factura_auto(texto: str) -> Optional[str]:
    """
    Detecta automáticamente el punto de venta y el número
    de factura.

    Devuelve el formato:

        PPPPP-NNNNNNNNN
    """
    patrones = [
        (
            r"\bN[º°o]?\s*[:\-]?\s*"
            r"0*(\d{1,5})\s*-\s*(\d{6,})\b"
        ),
        (
            r"\bNro\.?\s*[:\-]?\s*"
            r"0*(\d{1,5})\s*-\s*(\d{6,})\b"
        ),
        (
            r"\bNo\.?\s*[:\-]?\s*"
            r"0*(\d{1,5})\s*-\s*(\d{6,})\b"
        ),
        (
            r"\bNúm(?:ero)?\.?\s*[:\-]?\s*"
            r"0*(\d{1,5})\s*-\s*(\d{6,})\b"
        ),
        (
            r"\bFactura\s+N[º°o]?\s*[:\-]?\s*"
            r"0*(\d{1,5})\s*-\s*(\d{6,})\b"
        ),
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            flags=re.IGNORECASE
        )

        if match:
            return normalizar_numero_factura(
                match.group(1),
                match.group(2)
            )

    # Formato típico de comprobantes AFIP:
    #
    # Punto de Venta: 00001
    # Comp. Nro: 000000123
    match_afip = re.search(
        r"Punto\s+de\s+Venta\s*[:\-]?\s*"
        r"0*(\d{1,5})"
        r".*?"
        r"Comp\.?\s*Nro\.?\s*[:\-]?\s*(\d+)",
        texto,
        flags=re.IGNORECASE | re.DOTALL
    )

    if match_afip:
        return normalizar_numero_factura(
            match_afip.group(1),
            match_afip.group(2)
        )

    return None


# ----------------------------
# Helpers: nombre
# ----------------------------
def extraer_nombre_alumno(texto: str) -> Optional[str]:
    """
    Extrae el nombre correspondiente al campo Alumno/a.

    Ejemplo original:

        Alumno/a: 0261025403 MOMEÑO PENSA, MARTINA

    Resultado:

        MOMEÑO PENSA, MARTINA
    """
    # Algunos PDF utilizan espacios Unicode no separables.
    texto_limpio = texto.replace("\xa0", " ")

    match = re.search(
        r"^\s*Alumno\s*/\s*a\s*:\s*(.+?)\s*$",
        texto_limpio,
        flags=re.IGNORECASE | re.MULTILINE
    )

    if not match:
        return None

    contenido = match.group(1)

    # Normaliza espacios múltiples.
    contenido = re.sub(r"\s+", " ", contenido).strip()

    # Elimina el código numérico del alumno.
    contenido = re.sub(
        r"^\d{5,}\s+",
        "",
        contenido
    ).strip()

    return contenido if contenido else None


# ----------------------------
# Extractores por tipo
# ----------------------------
def extraer_datos_tipo1(texto: str) -> FacturaResult:
    """
    Factura del colegio:
    arancel, variable, reinscripción, etc.
    """
    fecha = re.search(
        r"Fecha:\s*(\d{2}/\d{2}/\d{4})",
        texto
    )

    numero = (
        extraer_numero_factura_auto(texto)
        or "No encontrado"
    )

    nombre = (
        extraer_nombre_alumno(texto)
        or "No encontrado"
    )

    vto = re.search(
        r"Vto:\s*(\d{2}/\d{2}/\d{4})"
        r".*?\$ ?([\d\.,]+)",
        texto,
        flags=re.DOTALL
    )

    monto = (
        vto.group(2)
        .replace(".", "")
        .replace(",", "")
        if vto
        else "No encontrado"
    )

    cuit_match = re.search(
        r"CUIT:\s*(\d{2})-(\d{8})-(\d{1})",
        texto
    )

    cuit = (
        "".join(cuit_match.groups())
        if cuit_match
        else "No encontrado"
    )

    return {
        "tipo": "Factura Colegio",
        "nombre": nombre,
        "fecha_emision": (
            fecha.group(1)
            if fecha
            else "No encontrada"
        ),
        "numero": numero,
        "monto": monto,
        "cuit": cuit,
    }


def extraer_datos_tipo2(texto: str) -> FacturaResult:
    """
    Factura de luz.
    """
    lsp = re.search(
        r"LSP B (\d{4})-(\d+)",
        texto
    )

    total = re.search(
        r"TOTAL A PAGAR \(1° vencimiento\)"
        r"\s*\$ ?([\d\.,]+)",
        texto
    )

    fecha = re.search(
        r"Capital Federal\s+(\d{2}/\d{2}/\d{4})",
        texto
    )

    nro = (
        normalizar_numero_factura(
            lsp.group(1),
            lsp.group(2)
        )
        if lsp
        else "No encontrada"
    )

    monto = (
        total.group(1)
        .replace(".", "")
        .replace(",", "")
        if total
        else "No encontrado"
    )

    cuit = "30655116512"

    return {
        "tipo": "Factura Luz",
        "fecha_emision": (
            fecha.group(1)
            if fecha
            else "No encontrada"
        ),
        "numero": nro,
        "monto": monto,
        "cuit": cuit,
    }


def extraer_datos_tipo3(
    doc: fitz.Document
) -> FacturaResult:
    """
    Factura del jardín con OCR por recortes.
    """
    texto: str = ""
    pagina_objetivo: Optional[fitz.Page] = None

    # Buscar página que contenga "Original".
    for pagina_any in doc:
        pagina = cast(fitz.Page, pagina_any)
        texto_pagina = cast(
            str,
            pagina.get_text("text")
        )

        if re.search(
            r"\boriginal\b",
            texto_pagina,
            flags=re.IGNORECASE
        ):
            texto = texto_pagina
            pagina_objetivo = pagina
            break

    # Fallback: buscar por nombre del jardín.
    if pagina_objetivo is None:
        for pagina_any in doc:
            pagina = cast(fitz.Page, pagina_any)
            texto_pagina = cast(
                str,
                pagina.get_text("text")
            )

            if "RECREANDO INFANCIAS" in texto_pagina:
                texto = texto_pagina
                pagina_objetivo = pagina
                break

    # Fallback final: utilizar la primera página.
    if pagina_objetivo is None:
        if len(doc) == 0:
            raise ValueError(
                "PDF vacío: no hay páginas para procesar."
            )

        pagina_objetivo = cast(
            fitz.Page,
            doc[0]
        )

        texto = cast(
            str,
            pagina_objetivo.get_text("text")
        )

    fechas = re.findall(
        r"\b\d{2}/\d{2}/\d{4}\b",
        texto
    )

    fecha = (
        fechas[0]
        if fechas
        else "No encontrada"
    )

    numero = (
        extraer_numero_factura_auto(texto)
        or "No encontrada"
    )

    # Renderiza la página como imagen.
    pix = pagina_objetivo.get_pixmap(dpi=300)
    imagen_bytes = pix.tobytes("png")

    imagen = Image.open(
        io.BytesIO(imagen_bytes)
    )

    # OCR del monto.
    crop_box_monto = (
        2200,
        1170,
        2500,
        1220
    )

    recorte_monto = imagen.crop(
        crop_box_monto
    )

    monto_ocr = pytesseract.image_to_string(
        recorte_monto,
        config=(
            "--psm 6 "
            "-c tessedit_char_whitelist=0123456789,."
        )
    ).strip()

    monto = (
        monto_ocr
        .replace(".", "")
        .replace(",", "")
    )

    # OCR del CUIT.
    crop_box_cuit = (
        1320,
        540,
        1820,
        590
    )

    recorte_cuit = imagen.crop(
        crop_box_cuit
    )

    cuit_ocr = pytesseract.image_to_string(
        recorte_cuit,
        config=(
            "--psm 6 "
            "-c tessedit_char_whitelist=0123456789"
        )
    ).strip()

    return {
        "tipo": "Factura Jardin",
        "fecha_emision": fecha,
        "numero": numero,
        "monto": (
            monto
            if monto
            else "No encontrado"
        ),
        "cuit": (
            cuit_ocr
            if cuit_ocr
            else "No encontrado"
        ),
    }


def extraer_datos_tipo4(texto: str) -> FacturaResult:
    """
    Factura de instituto de inglés.
    """
    numero = (
        extraer_numero_factura_auto(texto)
        or "No encontrado"
    )

    fecha = re.search(
        r"(\d{2}/\d{2}/\d{4})",
        texto
    )

    fecha_emision = (
        fecha.group(1)
        if fecha
        else "No encontrada"
    )

    imp_total = re.search(
        r"Importe Total:.*?\n([\d\.,]+)",
        texto
    )

    if imp_total:
        monto = (
            imp_total.group(1)
            .replace(".", "")
            .replace(",", ".")
        )
    else:
        importes = re.findall(
            r"(\d{4,}\.\d{2})",
            texto
        )

        monto = (
            importes[-1]
            if importes
            else "No encontrado"
        )

    cuit_match = re.search(
        r"CUIT:\s*(\d{2})-(\d{8})-(\d{1})",
        texto
    )

    cuit = (
        "".join(cuit_match.groups())
        if cuit_match
        else "No encontrado"
    )

    return {
        "tipo": "Factura Ingles",
        "fecha_emision": fecha_emision,
        "numero": numero,
        "monto": monto,
        "cuit": cuit,
    }


def extraer_datos_tipo5(
    doc: fitz.Document
) -> FacturaResult:
    """
    Factura Telecom.
    Procesa solamente la página 2.
    """
    if len(doc) < 2:
        raise ValueError(
            "Factura Telecom: esperaba al menos "
            "2 páginas y el PDF tiene menos."
        )

    pagina2 = cast(
        fitz.Page,
        doc[1]
    )

    texto = cast(
        str,
        pagina2.get_text("text")
    )

    match_fecha = re.search(
        r"Fecha de Emisi[oó]n\s*:?\s*"
        r"(\d{2}/\d{2}/\d{4})",
        texto
    )

    fecha_emision = (
        match_fecha.group(1)
        if match_fecha
        else "No encontrada"
    )

    match_vto = re.search(
        r"Fecha de Vencimiento\s*:?\s*"
        r"(\d{2}/\d{2}/\d{4})",
        texto
    )

    fecha_vencimiento = (
        match_vto.group(1)
        if match_vto
        else "No encontrada"
    )

    numero_factura = (
        extraer_numero_factura_auto(texto)
        or "No encontrado"
    )

    match_monto = re.search(
        r"TOTAL DE SERVICIOS DEL MES"
        r"\s*\$ ?([\d\.]+,\d{2})",
        texto
    )

    if match_monto:
        monto = (
            match_monto.group(1)
            .replace(".", "")
        )
    else:
        cualquier_monto = re.search(
            r"\$ ?([\d\.]+,\d{2})",
            texto
        )

        monto = (
            cualquier_monto.group(1)
            .replace(".", "")
            if cualquier_monto
            else "No encontrado"
        )

    match_cuit = re.search(
        r"C\.?U\.?I\.?T\.?:?\s*([\d-]+)",
        texto
    )

    cuit = (
        match_cuit.group(1).replace("-", "")
        if match_cuit
        else "No encontrado"
    )

    return {
        "tipo": "Factura Telecom",
        "fecha_emision": fecha_emision,
        "fecha_vencimiento": fecha_vencimiento,
        "numero": numero_factura,
        "monto": monto,
        "cuit": cuit,
    }


# ----------------------------
# Identificación del tipo
# ----------------------------
def identificar_tipo(texto: str) -> int:
    """
    Identifica el tipo de factura según palabras
    y expresiones presentes en el documento.
    """
    texto_minusculas = texto.lower()

    # Tipo 1: Colegio.
    if (
        "factura arancel" in texto_minusculas
        or "factura variable" in texto_minusculas
        or "factura reinscripci" in texto_minusculas
        or (
            "colegio y oratorio san francisco de"
            in texto_minusculas
        )
    ):
        return 1

    # Tipo 2: Luz.
    if (
        "liquidación de servicios públicos"
        in texto_minusculas
    ):
        return 2

    # Tipo 3: Jardín.
    if "recreando infancias" in texto_minusculas:
        return 3

    # Tipo 4: Inglés.
    if (
        "factura contado" in texto_minusculas
        and "sede central" in texto_minusculas
    ):
        return 4

    # Tipo 5: Telecom.
    if (
        "telecom argentina" in texto_minusculas
        and "total de servicios del mes"
        in texto_minusculas
    ):
        return 5

    return 0


# ----------------------------
# Procesamiento
# ----------------------------
def procesar_factura(
    path: Path
) -> Optional[FacturaResult]:
    """
    Abre un PDF, identifica el tipo de factura
    y ejecuta el extractor correspondiente.
    """
    doc: Optional[fitz.Document] = None

    try:
        doc = fitz.open(path)

        texto_completo = "\n".join(
            cast(
                str,
                cast(fitz.Page, pagina).get_text("text")
            )
            for pagina in doc
        )

        tipo = identificar_tipo(texto_completo)

        if tipo == 1:
            return extraer_datos_tipo1(
                texto_completo
            )

        if tipo == 2:
            return extraer_datos_tipo2(
                texto_completo
            )

        if tipo == 3:
            return extraer_datos_tipo3(doc)

        if tipo == 4:
            return extraer_datos_tipo4(
                texto_completo
            )

        if tipo == 5:
            return extraer_datos_tipo5(doc)

        print(
            f"[AVISO] Tipo de factura no identificado: "
            f"{path.name}"
        )

        return None

    except Exception as error:
        print(
            f"[ERROR] {path.name}: {error}"
        )
        return None

    finally:
        if doc is not None:
            doc.close()


def guardar_resultados_por_tipo(
    resultados: list[FacturaResult],
    carpeta_salida: Path
) -> None:
    """
    Agrupa los resultados por tipo y genera
    un archivo TXT para cada uno.
    """
    tipos: dict[str, list[FacturaResult]] = {}

    for resultado in resultados:
        tipo_key = (
            resultado["tipo"]
            .lower()
            .replace(" ", "_")
        )

        tipos.setdefault(
            tipo_key,
            []
        ).append(resultado)

    for tipo_key, registros in tipos.items():
        nombre_archivo = (
            f"facturas_{tipo_key}.txt"
        )

        ruta_archivo = (
            carpeta_salida / nombre_archivo
        )

        with open(
            ruta_archivo,
            "w",
            encoding="utf-8"
        ) as archivo:
            for registro in registros:
                archivo.write(
                    f"Tipo: "
                    f"{registro.get('tipo', 'No encontrado')}\n"
                )

                if "nombre" in registro:
                    archivo.write(
                        f"Alumno/a: "
                        f"{registro.get('nombre', 'No encontrado')}\n"
                    )

                archivo.write(
                    f"Fecha de emisión: "
                    f"{registro.get('fecha_emision', 'No encontrada')}\n"
                )

                if "fecha_vencimiento" in registro:
                    archivo.write(
                        f"Fecha de vencimiento: "
                        f"{registro['fecha_vencimiento']}\n"
                    )

                archivo.write(
                    f"Número de factura: "
                    f"{registro.get('numero', 'No encontrado')}\n"
                )

                archivo.write(
                    f"Monto: $"
                    f"{registro.get('monto', 'No encontrado')}\n"
                )

                archivo.write(
                    f"CUIT: "
                    f"{registro.get('cuit', 'No encontrado')}\n"
                )

                archivo.write(
                    "-" * 40 + "\n"
                )


def seleccionar_carpeta_y_ejecutar() -> None:
    """
    Abre el selector de carpetas, procesa los PDF
    y guarda los resultados.
    """
    carpeta_seleccionada = filedialog.askdirectory(
        title="Seleccioná la carpeta con los PDF"
    )

    if not carpeta_seleccionada:
        return

    carpeta = Path(carpeta_seleccionada)

    archivos_pdf = sorted(
        carpeta.glob("*.pdf")
    )

    if not archivos_pdf:
        messagebox.showwarning(
            "Sin archivos",
            "No se encontraron archivos PDF "
            "en la carpeta seleccionada."
        )
        return

    resultados: list[FacturaResult] = []

    for archivo_pdf in archivos_pdf:
        resultado = procesar_factura(
            archivo_pdf
        )

        if resultado is not None:
            resultados.append(resultado)

    if not resultados:
        messagebox.showwarning(
            "Sin resultados",
            "No pude extraer datos de ningún PDF "
            "en esa carpeta."
        )
        return

    guardar_resultados_por_tipo(
        resultados,
        carpeta
    )

    messagebox.showinfo(
        "¡Listo!",
        "Extracción completada.\n\n"
        "Los archivos TXT fueron guardados "
        "en la misma carpeta que los PDF."
    )

    ventana.destroy()
    sys.exit()


# ----------------------------
# GUI
# ----------------------------
ventana = tk.Tk()

ventana.title(
    "Extractor de Facturas PDF"
)

ventana.geometry(
    "460x220"
)

ventana.resizable(
    False,
    False
)

label = tk.Label(
    ventana,
    text=(
        "Extrae nombre, fecha, número, "
        "monto y CUIT de las facturas"
    ),
    font=("Arial", 12),
    wraplength=400
)

label.pack(
    pady=25
)

boton = tk.Button(
    ventana,
    text="Seleccionar carpeta y procesar",
    command=seleccionar_carpeta_y_ejecutar,
    font=("Arial", 12),
    padx=10,
    pady=5
)

boton.pack(
    pady=10
)

ventana.mainloop()
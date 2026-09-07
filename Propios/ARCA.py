from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pymupdf  # PyMuPDF


CAMPOS = [
    "Tipo",
    "Alumno/a",
    "Fecha de emisión",
    "Número de factura",
    "Monto",
    "CUIT",
]

# Campos visibles en la GUI.
# "Mes" se muestra también en el panel derecho y se puede copiar con doble click.
CAMPOS_GUI = ["Mes", *CAMPOS]

MESES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}

MESES_POR_NOMBRE = {nombre.lower(): numero for numero, nombre in MESES.items()}
# Aceptamos también la variante "setiembre", que aparece en algunos comprobantes.
MESES_POR_NOMBRE["setiembre"] = 9


def extraer_texto_pdf(pdf_path: Path) -> str:
    """Extrae el texto de todas las páginas de un PDF con PyMuPDF."""
    paginas: list[str] = []

    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            text_page = page.get_textpage()
            paginas.append(text_page.extractText())

    return "\n".join(paginas)


def normalizar_texto(texto: str) -> str:
    """Normaliza espacios raros sin destruir los saltos de línea."""
    texto = texto.replace("\xa0", " ")
    lineas = [re.sub(r"[ \t]+", " ", linea).strip() for linea in texto.splitlines()]
    return "\n".join(lineas)


def buscar_primero(patron: str, texto: str, flags=0, default="NO ENCONTRADO") -> str:
    match = re.search(patron, texto, flags)
    return match.group(1).strip() if match else default


def extraer_tipo(texto: str) -> str:
    # La letra del comprobante suele aparecer sola en una línea: A, B o C.
    match = re.search(r"(?m)^\s*([ABC])\s*$", texto)
    return match.group(1) if match else "NO ENCONTRADO"


def extraer_fecha(texto: str) -> str:
    # Intento principal: fecha explícitamente rotulada.
    match = re.search(r"Fecha(?:\s+de\s+emisi[oó]n)?\s*:?\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
    if match:
        return match.group(1)

    # Algunos PDFs separan la etiqueta "Fecha" del valor por el orden interno del PDF.
    # Como fallback, buscamos la primera fecha en la zona superior del documento.
    match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto[:1800])
    return match.group(1) if match else "NO ENCONTRADO"


def extraer_mes_factura(texto: str, fecha_emision: str) -> str:
    """
    Obtiene el mes al que corresponde la factura.

    Prioridad:
      1. Período explícito del comprobante, por ejemplo "MES DE MARZO DE 2026".
      2. Texto de pago, por ejemplo "PAGO MES DE Septiembre".
      3. Campo numérico "Mes: 9", si está presente de forma directa.
      4. Como fallback, usa el mes de la fecha de emisión.
    """
    nombre_mes = r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)"

    patrones_nombre = [
        rf"\bMES\s+DE\s+{nombre_mes}\s+DE\s+\d{{4}}\b",
        rf"\bPAGO\s+MES\s+DE\s+{nombre_mes}\b",
    ]

    for patron in patrones_nombre:
        match = re.search(patron, texto, re.I)
        if match:
            mes_texto = match.group(1).lower()
            numero_mes = MESES_POR_NOMBRE.get(mes_texto)
            if numero_mes:
                return MESES[numero_mes]

    # Algunos comprobantes muestran el período como un número.
    match = re.search(r"(?mi)^Mes\s*:\s*(0?[1-9]|1[0-2])\s*$", texto)
    if match:
        return MESES[int(match.group(1))]

    # Fallback: si el comprobante no declara otro período, tomamos el mes de emisión.
    match = re.fullmatch(r"\d{2}/(\d{2})/\d{4}", fecha_emision)
    if match:
        numero_mes = int(match.group(1))
        return MESES.get(numero_mes, "NO ENCONTRADO")

    return "NO ENCONTRADO"


def normalizar_numero_factura(numero: str) -> str:
    """
    Lleva el número de factura al formato fijo 00000-00000000.

    Ejemplos:
        0002-00316154   -> 00002-00316154
        2213-000206069  -> 02213-00206069
    """
    izquierda, derecha = numero.split("-", 1)

    # El punto de venta debe tener exactamente 5 dígitos.
    izquierda = izquierda.zfill(5)

    # Si el número de comprobante trae más de 8 dígitos, quitamos ceros
    # únicamente desde la izquierda hasta llegar a 8.
    while len(derecha) > 8 and derecha.startswith("0"):
        derecha = derecha[1:]

    # Si excepcionalmente viniera con menos de 8 dígitos, completamos con ceros.
    derecha = derecha.zfill(8)

    # No truncamos dígitos significativos: si después de quitar ceros a la izquierda
    # todavía hay más de 8, dejamos el valor visible para detectar el caso.
    return f"{izquierda}-{derecha}"


def extraer_numero_factura(texto: str) -> str:
    # Capturamos el número tal como viene en el PDF y luego lo normalizamos.
    match = re.search(r"\b(\d{1,5}-\d{6,12})\b", texto)
    if not match:
        return "NO ENCONTRADO"
    return normalizar_numero_factura(match.group(1))


def extraer_cuit(texto: str) -> str:
    # Extraemos CUIT/CUIL y devolvemos solamente los 11 dígitos, sin guiones.
    match = re.search(r"CUIT\s*:\s*(\d{2})-(\d{8})-(\d)", texto, re.I)
    if not match:
        return "NO ENCONTRADO"
    return "".join(match.groups())


def extraer_alumno(texto: str) -> str:
    # Formato tipo Salesianos: "Alumno/a: 0261025403 MOMEÑO PENSA, MARTINA"
    match = re.search(r"(?mi)^Alumno/a\s*:\s*(.+)$", texto)
    if match:
        alumno = match.group(1).strip()
        # Elimina un código numérico inicial si existe.
        alumno = re.sub(r"^\d+\s+", "", alumno).strip()
        return alumno

    # Formato AACI: por cómo está construido el PDF, primero aparecen varias etiquetas
    # y luego sus valores. Después de "Localidad:" los dos primeros valores son
    # Apellido y Nombre.
    if "AACI" in texto.upper() or "Factura Contado" in texto:
        bloque = texto.split("Localidad:", 1)
        if len(bloque) == 2:
            lineas = [l.strip() for l in bloque[1].splitlines() if l.strip()]
            if len(lineas) >= 2:
                apellido, nombre = lineas[0], lineas[1]
                return f"{apellido}, {nombre}"

    return "NO ENCONTRADO"


def normalizar_monto(monto: str) -> str:
    """
    Devuelve el monto como entero, sin separadores de miles ni decimales.

    Ejemplos:
        201.053,00 -> 201053
        311.612,00 -> 311612
        74800.00    -> 74800
    """
    monto = monto.replace("$", "").replace(" ", "").strip()

    if "," in monto:
        # Formato argentino: el punto separa miles y la coma separa decimales.
        parte_entera = monto.split(",", 1)[0]
        return parte_entera.replace(".", "")

    # Algunos sistemas generan el importe como 74800.00.
    # Si termina en punto + 2 decimales, ese punto actúa como separador decimal.
    if re.fullmatch(r"\d+\.\d{2}", monto):
        return monto.rsplit(".", 1)[0]

    # Fallback: eliminamos cualquier separador que no sea dígito.
    return re.sub(r"\D", "", monto)


def extraer_monto(texto: str) -> str:
    monto = None

    # Caso 1: documentos con "Importe Total".
    pos = texto.lower().find("importe total")
    if pos != -1:
        bloque = texto[pos:pos + 1400]
        # Captura importes con decimales en formato 74800.00 o 311.612,00.
        importes = re.findall(r"\b(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2}|\.\d{2})\b", bloque)
        if importes:
            # En AACI, por el orden interno del PDF, el importe total queda como
            # el último importe decimal del bloque de detalle.
            monto = importes[-1]

    # Caso 2: documentos donde el total aparece junto al vencimiento.
    if monto is None:
        match = re.search(
            r"\bVto\s*:\s*\d{2}/\d{2}/\d{4}[^\n$]*\$\s*([\d.]+,\d{2}|\d+\.\d{2})",
            texto,
            re.I,
        )
        if match:
            monto = match.group(1)

    # Fallback: "Son Pesos ... $ monto" dentro de una ventana acotada.
    if monto is None:
        pos = texto.lower().find("son pesos")
        if pos != -1:
            bloque = texto[pos:pos + 700]
            match = re.search(r"\$\s*([\d.]+,\d{2}|\d+\.\d{2})", bloque)
            if match:
                monto = match.group(1)

    return normalizar_monto(monto) if monto else "NO ENCONTRADO"


def parsear_factura(pdf_path: Path) -> dict:
    texto = normalizar_texto(extraer_texto_pdf(pdf_path))
    fecha_emision = extraer_fecha(texto)

    return {
        "Mes": extraer_mes_factura(texto, fecha_emision),
        "Tipo": extraer_tipo(texto),
        "Alumno/a": extraer_alumno(texto),
        "Fecha de emisión": fecha_emision,
        "Número de factura": extraer_numero_factura(texto),
        "Monto": extraer_monto(texto),
        "CUIT": extraer_cuit(texto),
    }


def guardar_txt(resultados: list[dict], salida: Path) -> None:
    """Guarda todas las facturas en un único TXT, una sección por PDF."""
    with salida.open("w", encoding="utf-8") as f:
        for i, factura in enumerate(resultados, start=1):
            if i > 1:
                f.write("\n" + "=" * 60 + "\n\n")
            f.write(f"Mes: {factura['Mes']}\n")
            for campo in CAMPOS:
                f.write(f"{campo}: {factura[campo]}\n")


def copiar_valor(event, root: tk.Tk, status_var: tk.StringVar):
    """Doble click sobre un Entry: copia TODO el valor al portapapeles."""
    widget = event.widget
    valor = widget.get()
    root.clipboard_clear()
    root.clipboard_append(valor)
    root.update()  # mantiene el contenido en clipboard al finalizar el evento
    widget.selection_range(0, tk.END)
    status_var.set(f"Copiado: {valor}")


def mostrar_gui(resultados: list[dict], txt_generado: Path) -> None:
    root = tk.Tk()
    root.title("Extractor de facturas")
    root.geometry("920x500")

    main = ttk.Frame(root, padding=12)
    main.pack(fill="both", expand=True)

    izquierda = ttk.Frame(main)
    izquierda.pack(side="left", fill="y", padx=(0, 16))

    derecha = ttk.Frame(main)
    derecha.pack(side="left", fill="both", expand=True)

    # En lugar de una Listbox plana usamos un Treeview.
    # De esta forma cada alumno aparece como grupo y debajo quedan sus facturas,
    # identificadas por el mes correspondiente.
    ttk.Label(izquierda, text="Facturas por alumno").pack(anchor="w")

    tree_frame = ttk.Frame(izquierda)
    tree_frame.pack(fill="both", expand=True, pady=(6, 0))

    arbol = ttk.Treeview(
        tree_frame,
        show="tree",
        selectmode="browse",
        height=18,
    )
    arbol.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(
        tree_frame,
        orient="vertical",
        command=arbol.yview,
    )
    scrollbar.pack(side="right", fill="y")
    arbol.configure(yscrollcommand=scrollbar.set)

    # Relaciona cada fila-hija del Treeview con la factura correspondiente.
    # Los nodos padre (alumnos) no apuntan a una factura concreta.
    factura_por_item: dict[str, int] = {}
    alumno_a_item: dict[str, str] = {}

    for indice, factura in enumerate(resultados):
        alumno = factura["Alumno/a"]

        if alumno not in alumno_a_item:
            item_alumno = arbol.insert(
                "",
                tk.END,
                text=alumno,
                open=True,
            )
            alumno_a_item[alumno] = item_alumno
        else:
            item_alumno = alumno_a_item[alumno]

        item_factura = arbol.insert(
            item_alumno,
            tk.END,
            text=factura["Mes"],
        )
        factura_por_item[item_factura] = indice

    status_var = tk.StringVar(value=f"TXT generado: {txt_generado.name}")
    status = ttk.Label(root, textvariable=status_var, anchor="w")
    status.pack(fill="x", padx=12, pady=(0, 10))

    entries = {}
    for fila, campo in enumerate(CAMPOS_GUI):
        ttk.Label(derecha, text=campo + ":").grid(
            row=fila,
            column=0,
            sticky="w",
            pady=7,
        )

        entry = ttk.Entry(derecha, width=65)
        entry.grid(
            row=fila,
            column=1,
            sticky="ew",
            padx=(10, 0),
            pady=7,
        )

        entry.bind(
            "<Double-Button-1>",
            lambda e: copiar_valor(e, root, status_var),
        )

        entries[campo] = entry

    derecha.columnconfigure(1, weight=1)

    ttk.Label(
        derecha,
        text="Doble click sobre cualquier valor para copiarlo completo al portapapeles.",
    ).grid(
        row=len(CAMPOS_GUI),
        column=0,
        columnspan=2,
        sticky="w",
        pady=(18, 0),
    )

    def cargar_factura(event=None):
        seleccion = arbol.selection()
        if not seleccion:
            return

        item_seleccionado = seleccion[0]

        # Si se seleccionó el nombre del alumno no cargamos nada:
        # solamente los hijos representan facturas individuales.
        indice = factura_por_item.get(item_seleccionado)
        if indice is None:
            return

        factura = resultados[indice]

        for campo, entry in entries.items():
            entry.config(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, factura[campo])
            entry.config(state="readonly")

    arbol.bind("<<TreeviewSelect>>", cargar_factura)

    # Seleccionamos automáticamente la primera factura disponible.
    for item_alumno in arbol.get_children():
        facturas_alumno = arbol.get_children(item_alumno)
        if facturas_alumno:
            primera_factura = facturas_alumno[0]
            arbol.selection_set(primera_factura)
            arbol.focus(primera_factura)
            arbol.see(primera_factura)
            cargar_factura()
            break

    root.mainloop()


def main():
    # Ocultamos la ventana principal mientras se elige la carpeta.
    selector = tk.Tk()
    selector.withdraw()

    carpeta = filedialog.askdirectory(title="Elegí la carpeta que contiene las facturas PDF")
    selector.destroy()

    if not carpeta:
        return

    carpeta = Path(carpeta)
    pdfs = sorted(carpeta.glob("*.pdf"))

    if not pdfs:
        messagebox.showerror("Sin PDFs", "No encontré archivos PDF en la carpeta seleccionada.")
        return

    resultados = []
    errores = []

    for pdf in pdfs:
        try:
            resultados.append(parsear_factura(pdf))
        except Exception as exc:
            errores.append(f"{pdf.name}: {exc}")

    if not resultados:
        messagebox.showerror("Error", "No se pudo procesar ninguna factura.")
        return

    salida = carpeta / "facturas_extraidas.txt"
    guardar_txt(resultados, salida)

    if errores:
        print("Se produjeron errores en algunos archivos:")
        for error in errores:
            print(" -", error)

    mostrar_gui(resultados, salida)


if __name__ == "__main__":
    main()

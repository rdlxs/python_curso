import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import time
import random

archivo_entrada = "Base_sin_nombres.xlsx"
archivo_salida = "Resultados_Nombres_Empresa.xlsx"

df = pd.read_excel(archivo_entrada)
dominios = df.iloc[:, 0]

nombres_empresa = []
dominios_fallidos = []

def extraer_nombre_copyright(html):
    texto = BeautifulSoup(html, "html.parser").get_text(separator=' ')
    matches = re.findall(r"Copyright(?: ©|\s)*[^\n]*?([A-Za-z0-9&\-,. ]{2,})", texto, flags=re.IGNORECASE)
    if matches:
        return matches[0].strip()
    return None

def guardar_parcial():
    df["Nombre Empresa"] = nombres_empresa
    df_fallidos = pd.DataFrame(dominios_fallidos, columns=["Dominios Fallidos"])
    with pd.ExcelWriter(archivo_salida) as writer:
        df.to_excel(writer, index=False, sheet_name="Con Nombres")
        df_fallidos.to_excel(writer, index=False, sheet_name="Fallidos")
    print(f"\n📁 Resultados guardados en: {archivo_salida}")

# Headers para simular navegador
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0 Safari/537.36"
    )
}

# Probar dominio con variantes (www / sin www)
def intentar_con_variantes(dominio):
    variantes = []

    # Limpieza inicial
    dominio_limpio = dominio.replace("http://", "").replace("https://", "").strip("/")

    if dominio_limpio.startswith("www."):
        variantes = [dominio_limpio, dominio_limpio[4:]]  # www.dominio -> [www.dominio, dominio]
    else:
        variantes = [dominio_limpio, "www." + dominio_limpio]

    for d in variantes:
        for esquema in ["http://", "https://"]:
            url = esquema + d
            try:
                resp = requests.get(url, timeout=10, headers=headers)
                if resp.status_code == 200:
                    return url, resp
            except:
                continue
    return None, None

# --- PROCESAMIENTO ---
try:
    for i, dominio in enumerate(dominios):
        try:
            url_final, resp = intentar_con_variantes(dominio)
            if resp:
                nombre = extraer_nombre_copyright(resp.text)
                if nombre:
                    print(f"[{i+1}/{len(dominios)}] ✅ {url_final}: {nombre}")
                    nombres_empresa.append(nombre)
                else:
                    print(f"[{i+1}/{len(dominios)}] ❌ {url_final}: No se encontró 'Copyright'")
                    nombres_empresa.append(None)
                    dominios_fallidos.append(dominio)
            else:
                print(f"[{i+1}/{len(dominios)}] ❌ {dominio}: No respondió ninguna variante")
                nombres_empresa.append(None)
                dominios_fallidos.append(dominio)

        except Exception as e:
            print(f"[{i+1}/{len(dominios)}] ❌ {dominio}: Error {str(e)}")
            nombres_empresa.append(None)
            dominios_fallidos.append(dominio)

        time.sleep(random.uniform(0.5, 1.5))

except KeyboardInterrupt:
    print("\n🛑 Interrupción manual detectada. Guardando lo procesado...")

finally:
    guardar_parcial()

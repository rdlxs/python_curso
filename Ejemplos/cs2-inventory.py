import json
import pandas as pd
import os

# 🔧 Cambiá esta ruta al JSON si es necesario
json_file = r"C:\Users\maxgt\OneDrive\Documents\GitHub\python_curso\Ejemplos\cs2_inventory.json"
xlsx_file = "cs2_inventory.xlsx"

# ✅ Validar si el archivo existe
if not os.path.isfile(json_file):
    print(f"❌ El archivo no existe: {json_file}")
    exit(1)

# 📥 Cargar el JSON
with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# 🔍 Separar assets y descriptions
assets = data.get("assets", [])
descriptions = {f"{d['classid']}_{d['instanceid']}": d for d in data.get("descriptions", [])}

inventory_items = []

for item in assets:
    key = f"{item['classid']}_{item['instanceid']}"
    desc = descriptions.get(key, {})

    # Obtener link de inspección (si existe)
    actions = desc.get("actions", [])
    inspect_link = next(
        (a.get("value") for a in actions if "Inspect" in a.get("name", "") and "value" in a),
        "N/A"
    )

    # Extraer rareza desde los tags (si está)
    rareza = "N/A"
    if desc.get("tags"):
        for tag in desc["tags"]:
            if tag.get("category") == "Rarity":
                rareza = tag.get("name", "N/A")
                break

    inventory_items.append({
        "Nombre": desc.get("market_name", "N/A"),
        "Tipo": desc.get("type", "N/A"),
        "Rareza": rareza,
        "Cantidad": item.get("amount", 1),
        "Inspect Link": inspect_link
    })

# 📊 Convertir a DataFrame
df = pd.DataFrame(inventory_items)

# 💾 Guardar como Excel
df.to_excel(xlsx_file, index=False)

print(f"✅ Inventario guardado como: {xlsx_file}")

import json
import pandas as pd

# Ruta al archivo JSON descargado
json_file = "cs2_inventory.json"
xlsx_file = "cs2_inventory.xlsx"

# Cargar el JSON
with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# 🧠 Estructura básica esperada desde Steam
# {
#     "assets": [...],
#     "descriptions": [...]
# }

# Mezclar assets con sus descripciones usando classid + instanceid
assets = data.get("assets", [])
descriptions = {f"{d['classid']}_{d['instanceid']}": d for d in data.get("descriptions", [])}

inventory_items = []

for item in assets:
    key = f"{item['classid']}_{item['instanceid']}"
    desc = descriptions.get(key, {})
    
    inventory_items.append({
        "Nombre": desc.get("market_name", "N/A"),
        "Tipo": desc.get("type", "N/A"),
        "Rareza": desc.get("tags", [{}])[-1].get("name", "N/A") if desc.get("tags") else "N/A",
        "Cantidad": item.get("amount", 1),
        "Inspect Link": next((a['value'] for a in desc.get("actions", []) if "Inspect" in a.get("name", "")), "N/A")
    })

# Convertir a DataFrame
df = pd.DataFrame(inventory_items)

# Guardar como Excel
df.to_excel(xlsx_file, index=False)

print(f"✅ Inventario guardado en: {xlsx_file}")
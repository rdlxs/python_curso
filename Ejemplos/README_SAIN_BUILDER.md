
# SAIN Assurance Graph Builder (Streamlit)

## Cómo ejecutar
1. Instala dependencias:
   ```bash
   pip install streamlit networkx matplotlib pandas
   ```
2. Ejecuta la app:
   ```bash
   streamlit run sain_builder.py
   ```

## Qué permite
- Agregar subservicios con tipo, ID y parámetros (clave/valor en JSON).
- Definir dependencias entre nodos (impacting/supporting).
- Exportar a JSON compatible con RFC 9418 (clave `ietf-service-assurance:subservices`).
- Importar un JSON existente para editarlo.
- Visualizar y descargar el grafo como PNG.

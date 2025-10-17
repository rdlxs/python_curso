
import json
import io
from typing import Dict, Any, List
import streamlit as st
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

st.set_page_config(page_title="SAIN Assurance Graph Builder", layout="wide")

st.title("🧭 SAIN Assurance Graph Builder")
st.caption("Crea y exporta grafos de aseguramiento (SAIN) en formato compatible con RFC 9418 y genera su gráfico.")

# --- Helpers ----------------------------
TYPE_PRESETS = {
    "service-instance-type": {
        "module": "ietf-service-assurance",
        "parameters_key": "service-instance-parameter",
        "hint": {"service": "simple-tunnel", "instance-name": "example"}
    },
    "ietf-service-assurance-interface:interface-type": {
        "module": "ietf-service-assurance-interface",
        "parameters_key": "ietf-service-assurance-interface:parameters",
        "hint": {"device": "Peer1", "interface": "tunnel0"}
    },
    "ietf-service-assurance-device:device-type": {
        "module": "ietf-service-assurance-device",
        "parameters_key": "ietf-service-assurance-device:parameters",
        "hint": {"device": "Peer1"}
    },
    "example-service-assurance-ip-connectivity:ip-connectivity-type": {
        "module": "example-service-assurance-ip-connectivity",
        "parameters_key": "example-service-assurance-ip-connectivity:parameters",
        "hint": {"device1": "Peer1", "address1": "2001:db8::1", "device2": "Peer2", "address2": "2001:db8::2"}
    },
    "example-service-assurance-is-is:is-is-type": {
        "module": "example-service-assurance-is-is",
        "parameters_key": "example-service-assurance-is-is:parameters",
        "hint": {"instance-name": "instance1"}
    },
    "custom:<namespace>:<type>": {
        "module": "custom",
        "parameters_key": "custom:parameters",
        "hint": {"key": "value"}
    }
}

COLOR_MAP = {
    "service-instance-type": "#4C78A8",
    "ietf-service-assurance-interface:interface-type": "#F58518",
    "ietf-service-assurance-device:device-type": "#54A24B",
    "example-service-assurance-ip-connectivity:ip-connectivity-type": "#E45756",
    "example-service-assurance-is-is:is-is-type": "#72B7B2",
}

def get_color(node_type: str) -> str:
    for t, c in COLOR_MAP.items():
        if node_type.startswith(t):
            return c
    return "#A0A0A0"

def ensure_state():
    if "nodes" not in st.session_state:
        st.session_state["nodes"] = {}  # id -> dict(node)
    if "dependencies" not in st.session_state:
        st.session_state["dependencies"] = []  # list of dict: {src_id, dst_id, dependency-type}
    if "selected_id" not in st.session_state:
        st.session_state["selected_id"] = ""

ensure_state()

# --- Sidebar: node editor ----------------
st.sidebar.header("➕ Agregar / Editar subservicio")
preset_type = st.sidebar.selectbox("Tipo (YANG 'type')", list(TYPE_PRESETS.keys()), index=0,
                                   help="Selecciona un tipo estándar o 'custom:<namespace>:<type>' para definir uno propio")

if preset_type.startswith("custom:"):
    custom_type = st.sidebar.text_input("Especificá el tipo completo (p.ej. vendor-x:foo-type)", value="vendor-x:foo-type")
    node_type = custom_type.strip() or "vendor-x:foo-type"
else:
    node_type = preset_type

node_id = st.sidebar.text_input("ID único del subservicio", value="service/instance1" if not st.session_state["selected_id"] else st.session_state["selected_id"])

preset = TYPE_PRESETS[preset_type]
params_key = preset["parameters_key"]
params_hint = preset["hint"]

params_text = st.sidebar.text_area(
    f"Parámetros ({params_key}) - JSON",
    value=json.dumps(params_hint, indent=2),
    height=160
)

dep_candidates = sorted(list(st.session_state["nodes"].keys()))
dep_selected = st.sidebar.multiselect("Dependencias (selecciona IDs existentes que impactan en este nodo)", dep_candidates)
dep_type = st.sidebar.selectbox("Tipo de dependencia", ["impacting", "supporting"], index=0)

col_btn1, col_btn2, col_btn3 = st.sidebar.columns(3)
add_btn = col_btn1.button("Guardar", use_container_width=True)
del_btn = col_btn2.button("Borrar", use_container_width=True)
clear_btn = col_btn3.button("Limpiar", use_container_width=True)

# Validation / Parse parameters
def parse_params(text: str) -> Dict[str, Any]:
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except Exception as e:
        st.sidebar.error(f"JSON inválido en parámetros: {e}")
        return {}

if add_btn:
    if not node_id.strip():
        st.sidebar.error("El ID no puede estar vacío.")
    else:
        if node_id != st.session_state.get("selected_id") and node_id in st.session_state["nodes"]:
            st.sidebar.error("Ya existe un nodo con ese ID.")
        else:
            params = parse_params(params_text)
            if params is not None:
                st.session_state["nodes"][node_id] = {
                    "id": node_id,
                    "type": node_type,
                    "parameters_key": params_key,
                    "parameters": params,
                }
                # Actualizar dependencias: eliminamos previas dirigidas a este nodo y re-agregamos
                st.session_state["dependencies"] = [d for d in st.session_state["dependencies"] if d["src_id"] != node_id]
                for dst in dep_selected:
                    st.session_state["dependencies"].append({
                        "src_id": node_id,
                        "dst_id": dst,
                        "dependency-type": dep_type
                    })
                st.session_state["selected_id"] = node_id
                st.sidebar.success("Nodo guardado.")

if del_btn and node_id in st.session_state["nodes"]:
    st.session_state["nodes"].pop(node_id, None)
    st.session_state["dependencies"] = [d for d in st.session_state["dependencies"] if d["src_id"] != node_id and d["dst_id"] != node_id]
    st.session_state["selected_id"] = ""
    st.sidebar.warning("Nodo eliminado.")

if clear_btn:
    st.session_state["selected_id"] = ""
    st.experimental_rerun()

# --- Main: Table and selection -------------
left, right = st.columns([1.1, 1.2], gap="large")

with left:
    st.subheader("📋 Subservicios")
    if st.session_state["nodes"]:
        df = pd.DataFrame([{
            "id": n["id"],
            "type": n["type"],
            "parameters_key": n["parameters_key"],
            "parameters": json.dumps(n["parameters"], ensure_ascii=False)
        } for n in st.session_state["nodes"].values()]).sort_values("id")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Aún no hay subservicios. Usá el panel izquierdo para agregar.")

    st.subheader("🔗 Dependencias")
    if st.session_state["dependencies"]:
        df_dep = pd.DataFrame(st.session_state["dependencies"]).sort_values(["src_id", "dst_id"])
        st.dataframe(df_dep, use_container_width=True)
    else:
        st.info("Sin dependencias definidas.")

    # Import / Export JSON
    st.markdown("---")
    st.subheader("📦 Importar / Exportar JSON (RFC 9418)")
    # Export
    def build_json() -> Dict[str, Any]:
        subs = []
        for node in st.session_state["nodes"].values():
            entry = {
                "type": node["type"],
                "id": node["id"],
            }
            # attach parameters if any
            if node["parameters"]:
                entry[node["parameters_key"]] = node["parameters"]
            # dependencies
            deps = [d for d in st.session_state["dependencies"] if d["src_id"] == node["id"]]
            if deps:
                entry["dependencies"] = {"dependency": [{
                    "type": st.session_state["nodes"][d["dst_id"]]["type"] if d["dst_id"] in st.session_state["nodes"] else "unknown",
                    "id": d["dst_id"],
                    "dependency-type": d["dependency-type"]
                } for d in deps]}
            subs.append(entry)
        return {"ietf-service-assurance:subservices": {"subservice": subs}}

    export_json = json.dumps(build_json(), indent=2, ensure_ascii=False)
    st.download_button("⬇️ Descargar JSON", data=export_json.encode("utf-8"), file_name="assurance_graph.json", mime="application/json")

    # Import
    uploaded = st.file_uploader("Importar JSON", type=["json"], help="Importa una instancia compatible con RFC 9418")
    if uploaded is not None:
        try:
            data = json.load(uploaded)
            subs = data.get("ietf-service-assurance:subservices", {}).get("subservice", [])
            nodes, deps = {}, []
            for s in subs:
                sid = s["id"]
                stype = s["type"]
                # try to guess params_key among known ones
                pk = None
                for preset in TYPE_PRESETS.values():
                    if stype.startswith(preset.get("module", "")) or stype == "service-instance-type" and preset["parameters_key"] == "service-instance-parameter":
                        if preset["parameters_key"] in s:
                            pk = preset["parameters_key"]
                            break
                if pk is None:
                    # fallback: pick first key ending with ':parameters' or well-known keys
                    for k in s.keys():
                        if k.endswith(":parameters") or k in ("service-instance-parameter",):
                            pk = k
                            break
                params = s.get(pk, {})
                nodes[sid] = {"id": sid, "type": stype, "parameters_key": pk or "custom:parameters", "parameters": params}
                for d in s.get("dependencies", {}).get("dependency", []):
                    deps.append({"src_id": sid, "dst_id": d["id"], "dependency-type": d.get("dependency-type", "impacting")})
            st.session_state["nodes"] = nodes
            st.session_state["dependencies"] = deps
            st.success("JSON importado correctamente.")
        except Exception as e:
            st.error(f"No se pudo importar el JSON: {e}")

with right:
    st.subheader("🕸️ Visualización del grafo")
    G = nx.DiGraph()
    for node_id, node in st.session_state["nodes"].items():
        G.add_node(node_id, type=node["type"])
    for d in st.session_state["dependencies"]:
        if d["src_id"] in G.nodes and d["dst_id"] in G.nodes:
            G.add_edge(d["src_id"], d["dst_id"], dep=d["dependency-type"])

    if len(G.nodes) == 0:
        st.info("Agrega subservicios para ver el grafo.")
    else:
        # Layout
        pos = nx.spring_layout(G, k=0.8, iterations=200, seed=42)
        plt.figure(figsize=(8, 6))
        node_colors = [get_color(G.nodes[n]["type"]) for n in G.nodes]
        nx.draw(G, pos, with_labels=True, node_color=node_colors, node_size=1600, edgecolors="black", font_size=8, arrows=True)
        # Edge labels (dependency-type)
        edge_labels = {(u, v): G.edges[u, v].get("dep", "") for u, v in G.edges}
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)
        plt.title("Assurance Graph")
        plt.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=160)
        st.pyplot(plt.gcf())
        st.download_button("⬇️ Descargar PNG del grafo", data=buf.getvalue(), file_name="assurance_graph.png", mime="image/png")

st.markdown("---")
st.caption("Sugerencia: usá IDs estables y tipos con namespace (p.ej. `ietf-service-assurance-interface:interface-type`). Las dependencias se dibujan como aristas dirigidas desde el nodo dependiente hacia el que **impacta**.")

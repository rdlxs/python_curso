
import json
import io
from typing import Dict, Any, List, Tuple
import streamlit as st
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

st.set_page_config(page_title="SAIN Assurance Graph Builder", layout="wide")

st.title("🧭 SAIN Assurance Graph Builder — Pro")
st.caption("Construí grafos de aseguramiento (RFC 9418 / SAIN), validá dependencias, importá/exportá JSON, y generá visualizaciones.")

# =========================
# Presets y utilidades
# =========================
TYPE_PRESETS = {
    # Base
    "service-instance-type": {
        "module": "ietf-service-assurance",
        "parameters_key": "service-instance-parameter",
        "hint": {"service": "simple-tunnel", "instance-name": "example"}
    },
    # Extensiones RFC 9418
    "ietf-service-assurance-interface:interface-type": {
        "module": "ietf-service-assurance-interface",
        "parameters_key": "ietf-service-assurance-interface:parameters",
        "hint": {"device": "Peer1", "interface": "GigabitEthernet0/0/0"}
    },
    "ietf-service-assurance-device:device-type": {
        "module": "ietf-service-assurance-device",
        "parameters_key": "ietf-service-assurance-device:parameters",
        "hint": {"device": "Router1"}
    },
    # Ejemplos del RFC
    "example-service-assurance-ip-connectivity:ip-connectivity-type": {
        "module": "example-service-assurance-ip-connectivity",
        "parameters_key": "example-service-assurance-ip-connectivity:parameters",
        "hint": {"device1": "Router1", "address1": "2001:db8::1", "device2": "Router2", "address2": "2001:db8::2"}
    },
    "example-service-assurance-is-is:is-is-type": {
        "module": "example-service-assurance-is-is",
        "parameters_key": "example-service-assurance-is-is:parameters",
        "hint": {"instance-name": "isis-core"}
    },
    # Comunes en aseguramiento (no normativos; útiles como atajos)
    "example:srpm-latency-type": {
        "module": "example",
        "parameters_key": "example:parameters",
        "hint": {"src": "Router1", "dst": "Router2", "policy": "SRv6-TE1"}
    },
    "example:bfd-session-type": {
        "module": "example",
        "parameters_key": "example:parameters",
        "hint": {"device": "Router1", "neighbor": "Router2", "intf": "Tunnel0"}
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
    "example:srpm-latency-type": "#B279A2",
    "example:bfd-session-type": "#FF9DA6",
}

DEPENDENCY_TYPES = [
    ("impacting", "El origen depende del destino; si el destino se degrada, impacta al origen."),
    ("supporting", "El origen aporta información/telemetría al destino; no es dependencia funcional."),
]

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

# =========================
# Sidebar — Editor de nodos
# =========================
st.sidebar.header("➕ Agregar / Editar subservicio")

preset_type = st.sidebar.selectbox(
    "Tipo (YANG 'type')",
    list(TYPE_PRESETS.keys()),
    help="Elegí un tipo estándar o 'custom:<namespace>:<type>' para definir uno propio."
)

if preset_type.startswith("custom:"):
    node_type = st.sidebar.text_input("Tipo completo (p.ej. vendor-x:foo-type)", value="vendor-x:foo-type")
    parameters_key = st.sidebar.text_input("Clave de parámetros (p.ej. vendor-x:parameters)", value="vendor-x:parameters")
    params_hint = {"key": "value"}
else:
    preset = TYPE_PRESETS[preset_type]
    node_type = preset_type
    parameters_key = preset["parameters_key"]
    params_hint = preset["hint"]

node_id = st.sidebar.text_input("ID único del subservicio", value=st.session_state.get("selected_id") or "service/instance1")

params_text = st.sidebar.text_area(
    f"Parámetros ({parameters_key}) - JSON",
    value=json.dumps(params_hint, indent=2),
    height=160
)

# Dependencias
with st.sidebar.expander("🔗 Dependencias del nodo (aristas salientes)", expanded=True):
    dep_candidates = sorted([k for k in st.session_state["nodes"].keys() if k != node_id])
    dep_selected = st.multiselect("Seleccioná IDs existentes que impactan o soportan a este nodo (destino)", dep_candidates)
    dep_type_label = st.selectbox("Tipo de dependencia", [f"{k} — {v}" for k, v in DEPENDENCY_TYPES], index=0,
                                  help="impacting: dependencia funcional; supporting: aporte de señal/telemetría.")
    dep_type = dep_type_label.split(" — ")[0]

col_btn1, col_btn2, col_btn3 = st.sidebar.columns(3)
save_btn = col_btn1.button("Guardar", use_container_width=True)
del_btn = col_btn2.button("Borrar", use_container_width=True)
clear_btn = col_btn3.button("Limpiar", use_container_width=True)

def parse_params(text: str) -> Dict[str, Any]:
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except Exception as e:
        st.sidebar.error(f"JSON inválido en parámetros: {e}")
        return {}

if save_btn:
    if not node_id.strip():
        st.sidebar.error("El ID no puede estar vacío.")
    else:
        # Permitir renombrado: si cambia el ID seleccionado, actualizar dependencias referidas
        prev_id = st.session_state.get("selected_id")
        params = parse_params(params_text)
        if params is not None:
            # si renombró, trasladar dependencias y nodo
            if prev_id and prev_id != node_id and prev_id in st.session_state["nodes"]:
                # mover nodo
                node_prev = st.session_state["nodes"].pop(prev_id)
                # actualizar dependencias que apuntaban al viejo ID
                for d in st.session_state["dependencies"]:
                    if d["src_id"] == prev_id:
                        d["src_id"] = node_id
                    if d["dst_id"] == prev_id:
                        d["dst_id"] = node_id
            # guardar/crear
            st.session_state["nodes"][node_id] = {
                "id": node_id,
                "type": node_type,
                "parameters_key": parameters_key,
                "parameters": params,
            }
            # actualizar dependencias salientes del nodo
            st.session_state["dependencies"] = [d for d in st.session_state["dependencies"] if d["src_id"] != node_id]
            for dst in dep_selected:
                if dst != node_id:
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
    st.rerun()

# =========================
# Main — Tablas, validación y export
# =========================
left, mid, right = st.columns([1.1, 1.0, 1.2], gap="large")

with left:
    st.subheader("📋 Subservicios")
    if st.session_state["nodes"]:
        df = pd.DataFrame([{
            "id": n["id"],
            "type": n["type"],
            "parameters_key": n["parameters_key"],
            "parameters": json.dumps(n["parameters"], ensure_ascii=False)
        } for n in st.session_state["nodes"].values()]).sort_values("id")
        st.dataframe(df, use_container_width=True, height=260)
    else:
        st.info("Aún no hay subservicios. Usá el panel izquierdo para agregar.")

    st.subheader("🔗 Dependencias")
    if st.session_state["dependencies"]:
        df_dep = pd.DataFrame(st.session_state["dependencies"]).sort_values(["src_id", "dst_id"])
        st.dataframe(df_dep, use_container_width=True, height=220)
    else:
        st.info("Sin dependencias definidas.")

    # Import / Export JSON
    st.markdown("---")
    st.subheader("📦 Importar / Exportar JSON (RFC 9418)")

    def build_json() -> Dict[str, Any]:
        subs = []
        for node in st.session_state["nodes"].values():
            entry = {"type": node["type"], "id": node["id"]}
            if node["parameters"]:
                entry[node["parameters_key"]] = node["parameters"]
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
                # adivinar parameters_key
                pk = None
                known_keys = {preset["parameters_key"] for preset in TYPE_PRESETS.values() if "parameters_key" in preset}
                for k in s.keys():
                    if k in known_keys or k.endswith(":parameters") or k == "service-instance-parameter":
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

with mid:
    st.subheader("🧪 Validación")
    # Construir grafo para validar
    G = nx.DiGraph()
    for node_id, node in st.session_state["nodes"].items():
        G.add_node(node_id, type=node["type"])
    for d in st.session_state["dependencies"]:
        if d["src_id"] in G.nodes and d["dst_id"] in G.nodes:
            G.add_edge(d["src_id"], d["dst_id"], dep=d["dependency-type"])

    issues = []
    # 1) Nodos huérfanos (sin edges ni entrantes ni salientes)
    for n in G.nodes():
        if G.in_degree(n) == 0 and G.out_degree(n) == 0:
            issues.append(("warning", f"Nodo '{n}' está aislado (sin dependencias)."))

    # 2) Ciclos (SAIN asume DAG)
    try:
        cycles = list(nx.simple_cycles(G))
        if cycles:
            for c in cycles:
                issues.append(("error", f"Ciclo detectado: {' -> '.join(c + [c[0]])}"))
    except Exception:
        pass

    if issues:
        for lvl, msg in issues:
            if lvl == "error":
                st.error(msg)
            elif lvl == "warning":
                st.warning(msg)
    else:
        st.success("Sin problemas detectados. El grafo es acíclico.")

    # Export DOT (Graphviz)
    def to_dot(G: nx.DiGraph) -> str:
        lines = ["digraph assurance {"]
        for n, data in G.nodes(data=True):
            color = get_color(data.get("type", ""))
            label = n.replace('"', '\\"')
            lines.append(f'  "{label}" [style=filled, fillcolor="{color}", shape=box];')
        for u, v, data in G.edges(data=True):
            dep = data.get("dep", "")
            lines.append(f'  "{u.replace(chr(34),"\\\"")}" -> "{v.replace(chr(34),"\\\"")}" [label="{dep}"];')
        lines.append("}")
        return "\n".join(lines)

    dot_str = to_dot(G)
    st.download_button("⬇️ Descargar Graphviz .dot", data=dot_str.encode("utf-8"), file_name="assurance_graph.dot", mime="text/vnd.graphviz")

with right:
    st.subheader("🕸️ Visualización del grafo")
    # Reusar G de validación
    if len(G.nodes) == 0:
        st.info("Agrega subservicios para ver el grafo.")
    else:
        # Layout spring (general) o topológico si es DAG
        try:
            order = list(nx.topological_sort(G))
            # coordenadas por nivel
            levels = {}
            for n in order:
                levels[n] = max([levels.get(p, 0) + 1 for p in G.predecessors(n)] + [0])
            pos = {}
            for lvl in sorted(set(levels.values())):
                same = [n for n, l in levels.items() if l == lvl]
                for i, n in enumerate(same):
                    pos[n] = (i, -lvl)
        except nx.NetworkXUnfeasible:
            pos = nx.spring_layout(G, k=0.8, iterations=250, seed=42)

        plt.figure(figsize=(9.5, 7.2))
        node_colors = [get_color(G.nodes[n]["type"]) for n in G.nodes]
        nx.draw(G, pos, with_labels=True, node_color=node_colors, node_size=1700, edgecolors="black", font_size=8, arrows=True)
        edge_labels = {(u, v): G.edges[u, v].get("dep", "") for u, v in G.edges}
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)
        # Leyenda
        legend_items = {}
        for t, c in COLOR_MAP.items():
            legend_items[t] = c
        y0 = 1.02
        for i, (t, c) in enumerate(legend_items.items()):
            plt.text(0.0, y0 - i*0.05, f"■ {t}", transform=plt.gca().transAxes, fontsize=8, bbox=dict(facecolor=c, alpha=0.5, pad=1))
        plt.title("Assurance Graph")
        plt.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=160)
        st.pyplot(plt.gcf())
        st.download_button("⬇️ Descargar PNG del grafo", data=buf.getvalue(), file_name="assurance_graph.png", mime="image/png")

st.markdown("---")
with st.expander("ℹ️ Ayuda rápida"):
    st.markdown("""
**Tipos de dependencia**  
- **impacting**: el **origen depende** del **destino**; si el destino se degrada, impacta al origen.  
- **supporting**: el **origen aporta** telemetría/señal al **destino**; no es dependencia funcional.

**Convenciones de ID**  
Usá IDs estables y significativos (p. ej. `interface/Router1/Gi0-0-0`, `device/Router1`, `service/l3vpn/clienteX`).

**Compatibilidad RFC 9418**  
La exportación JSON utiliza la raíz `ietf-service-assurance:subservices` con elementos `subservice` que incluyen `type`, `id`, `dependencies/dependency[]` y la clave de parámetros específica del módulo (por ejemplo `service-instance-parameter` o `<namespace>:parameters`).

**Validación**  
El validador detecta ciclos (el grafo debería ser un **DAG**) y nodos aislados. También podés exportar a **Graphviz .dot** para diagramación avanzada.
""")

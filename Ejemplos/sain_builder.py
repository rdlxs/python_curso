
import json
import io
from typing import Dict, Any, List, Tuple
import streamlit as st
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

st.set_page_config(page_title="SAIN Assurance Graph Builder — Pro+", layout="wide")

st.title("🧭 SAIN Assurance Graph Builder — Pro+")
st.caption("Presets de servicios (L2VPN/L3VPN, SR‑MPLS/SRv6, BFD, SR‑PM) + validación estructural y validación opcional contra YANG (si tenés yangson).")

# =========================
# Presets y utilidades
# =========================
TYPE_PRESETS = {
    # Base (RFC 9418)
    "service-instance-type": {
        "module": "ietf-service-assurance",
        "parameters_key": "service-instance-parameter",
        "hint": {"service": "l2vpn", "instance-name": "clienteA-p2p-01"}
    },
    "ietf-service-assurance-interface:interface-type": {
        "module": "ietf-service-assurance-interface",
        "parameters_key": "ietf-service-assurance-interface:parameters",
        "hint": {"device": "PE1", "interface": "GigabitEthernet0/0/0"}
    },
    "ietf-service-assurance-device:device-type": {
        "module": "ietf-service-assurance-device",
        "parameters_key": "ietf-service-assurance-device:parameters",
        "hint": {"device": "PE1"}
    },
    # Ejemplos oficiales del RFC
    "example-service-assurance-ip-connectivity:ip-connectivity-type": {
        "module": "example-service-assurance-ip-connectivity",
        "parameters_key": "example-service-assurance-ip-connectivity:parameters",
        "hint": {"device1": "PE1", "address1": "2001:db8::1", "device2": "PE2", "address2": "2001:db8::2"}
    },
    "example-service-assurance-is-is:is-is-type": {
        "module": "example-service-assurance-is-is",
        "parameters_key": "example-service-assurance-is-is:parameters",
        "hint": {"instance-name": "isis-core"}
    },
    # Presets de servicio (no normativos, útiles para armar grafos)
    "preset:service-l2vpn": {
        "module": "preset",
        "parameters_key": "preset:parameters",
        "hint": {"customer": "ClienteA", "site-a": "PE1.Gi0/0/0", "site-b": "PE2.Gi0/0/1"}
    },
    "preset:service-l3vpn": {
        "module": "preset",
        "parameters_key": "preset:parameters",
        "hint": {"vrf": "VRF-ClienteB", "pe-a": "PE1", "pe-b": "PE2"}
    },
    "preset:sr-mpls-lsp": {
        "module": "preset",
        "parameters_key": "preset:parameters",
        "hint": {"src": "PE1", "dst": "PE2", "policy": "SR-MPLS-PE1-PE2"}
    },
    "preset:sr-v6-policy": {
        "module": "preset",
        "parameters_key": "preset:parameters",
        "hint": {"src": "PE1", "dst": "PE2", "policy": "SRv6-Policy-1"}
    },
    "preset:bfd-session": {
        "module": "preset",
        "parameters_key": "preset:parameters",
        "hint": {"device": "PE1", "neighbor": "PE2", "intf": "Tunnel0"}
    },
    "preset:srpm-latency": {
        "module": "preset",
        "parameters_key": "preset:parameters",
        "hint": {"src": "PE1", "dst": "PE2", "policy": "SRv6-Policy-1", "threshold_ms": 200}
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
    "preset:service-l2vpn": "#A0CBE8",
    "preset:service-l3vpn": "#FFBE7D",
    "preset:sr-mpls-lsp": "#59A14F",
    "preset:sr-v6-policy": "#8CD17D",
    "preset:bfd-session": "#B6992D",
    "preset:srpm-latency": "#F28E2B",
}

DEPENDENCY_TYPES = [
    ("impacting", "El origen depende del destino; si el destino se degrada, impacta al origen."),
    ("supporting", "El origen aporta información/telemetría al destino; no es dependencia funcional."),
]

# Reglas de validación por tipo (ligeras; para validación YANG estricta ver sección más abajo)
PARAM_RULES = {
    "service-instance-type": {"required": ["service", "instance-name"], "params_key": "service-instance-parameter"},
    "ietf-service-assurance-interface:interface-type": {"required": ["device", "interface"], "params_key": "ietf-service-assurance-interface:parameters"},
    "ietf-service-assurance-device:device-type": {"required": ["device"], "params_key": "ietf-service-assurance-device:parameters"},
    "example-service-assurance-ip-connectivity:ip-connectivity-type": {"required": ["device1", "address1", "device2", "address2"], "params_key": "example-service-assurance-ip-connectivity:parameters"},
    "example-service-assurance-is-is:is-is-type": {"required": ["instance-name"], "params_key": "example-service-assurance-is-is:parameters"},
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

# =========================
# Sidebar — Editor de nodos
# =========================
st.sidebar.header("➕ Agregar / Editar subservicio")

preset_type = st.sidebar.selectbox(
    "Tipo (YANG 'type' o preset)",
    list(TYPE_PRESETS.keys()),
    help="Elegí un tipo estándar, un preset de servicio, o 'custom:<namespace>:<type>' para definir uno propio."
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
            if prev_id and prev_id != node_id and prev_id in st.session_state["nodes"]:
                # mover nodo
                st.session_state["nodes"].pop(prev_id)
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
# Presets de servicio (wizard)
# =========================
st.markdown("### 🧪 Generadores de presets de servicio (opcional)")
with st.expander("Agregar un preset completo al grafo"):
    preset_choice = st.selectbox(
        "Elegí un preset",
        ["L2VPN P2P básico", "L3VPN básico", "SR‑MPLS LSP", "SRv6 Policy", "BFD Session", "SR‑PM Latency"]
    )
    colp1, colp2, colp3 = st.columns(3)
    if preset_choice == "L2VPN P2P básico":
        cust = colp1.text_input("Cliente", "ClienteA")
        pe_a = colp2.text_input("PE A", "PE1")
        pe_b = colp3.text_input("PE B", "PE2")
        int_a = colp1.text_input("Interfaz A", "GigabitEthernet0/0/0")
        int_b = colp2.text_input("Interfaz B", "GigabitEthernet0/0/1")
        if st.button("➕ Insertar preset L2VPN"):
            # servicio
            st.session_state["nodes"][f"service/l2vpn/{cust}"] = {
                "id": f"service/l2vpn/{cust}",
                "type": "service-instance-type",
                "parameters_key": "service-instance-parameter",
                "parameters": {"service": "l2vpn", "instance-name": cust}
            }
            # interfaces
            a_int = f"interface/{pe_a}/{int_a}"
            b_int = f"interface/{pe_b}/{int_b}"
            for dev, intf, nid in [(pe_a, int_a, a_int), (pe_b, int_b, b_int)]:
                st.session_state["nodes"][nid] = {
                    "id": nid,
                    "type": "ietf-service-assurance-interface:interface-type",
                    "parameters_key": "ietf-service-assurance-interface:parameters",
                    "parameters": {"device": dev, "interface": intf}
                }
                # dependencias interface->device
                dev_id = f"device/{dev}"
                st.session_state["nodes"][dev_id] = {
                    "id": dev_id,
                    "type": "ietf-service-assurance-device:device-type",
                    "parameters_key": "ietf-service-assurance-device:parameters",
                    "parameters": {"device": dev}
                }
                st.session_state["dependencies"].append({"src_id": nid, "dst_id": dev_id, "dependency-type": "impacting"})
            # servicio depende de interfaces
            st.session_state["dependencies"].append({"src_id": f"service/l2vpn/{cust}", "dst_id": a_int, "dependency-type": "impacting"})
            st.session_state["dependencies"].append({"src_id": f"service/l2vpn/{cust}", "dst_id": b_int, "dependency-type": "impacting"})
            st.success("Preset L2VPN agregado.")

    if preset_choice == "L3VPN básico":
        vrf = colp1.text_input("VRF", "VRF-ClienteB")
        pe_a = colp2.text_input("PE A", "PE1")
        pe_b = colp3.text_input("PE B", "PE2")
        if st.button("➕ Insertar preset L3VPN"):
            sid = f"service/l3vpn/{vrf}"
            st.session_state["nodes"][sid] = {"id": sid, "type": "service-instance-type",
                "parameters_key": "service-instance-parameter",
                "parameters": {"service": "l3vpn", "instance-name": vrf}}
            # conectividad IP y ISIS como ejemplo
            conn_id = f"ipconnect/{pe_a}-{pe_b}"
            st.session_state["nodes"][conn_id] = {"id": conn_id,
                "type": "example-service-assurance-ip-connectivity:ip-connectivity-type",
                "parameters_key": "example-service-assurance-ip-connectivity:parameters",
                "parameters": {"device1": pe_a, "address1": "2001:db8::1", "device2": pe_b, "address2": "2001:db8::2"}}
            isis_id = f"isis/{pe_a}-{pe_b}"
            st.session_state["nodes"][isis_id] = {"id": isis_id,
                "type": "example-service-assurance-is-is:is-is-type",
                "parameters_key": "example-service-assurance-is-is:parameters",
                "parameters": {"instance-name": "isis-core"}}
            st.session_state["dependencies"] += [
                {"src_id": sid, "dst_id": conn_id, "dependency-type": "impacting"},
                {"src_id": conn_id, "dst_id": isis_id, "dependency-type": "impacting"}
            ]
            st.success("Preset L3VPN agregado.")

    if preset_choice == "SR‑MPLS LSP":
        src = colp1.text_input("Src", "PE1")
        dst = colp2.text_input("Dst", "PE2")
        pol = colp3.text_input("Policy", "SR-MPLS-PE1-PE2")
        if st.button("➕ Insertar preset SR‑MPLS"):
            sid = f"service/sr-mpls/{pol}"
            st.session_state["nodes"][sid] = {"id": sid, "type": "service-instance-type",
                "parameters_key": "service-instance-parameter",
                "parameters": {"service": "sr-mpls", "instance-name": pol}}
            bfd = f"bfd/{src}-{dst}"
            st.session_state["nodes"][bfd] = {"id": bfd, "type": "preset:bfd-session",
                "parameters_key": "preset:parameters",
                "parameters": {"device": src, "neighbor": dst, "intf": "Tunnel0"}}
            st.session_state["dependencies"] += [
                {"src_id": sid, "dst_id": bfd, "dependency-type": "supporting"},
            ]
            st.success("Preset SR‑MPLS agregado.")

    if preset_choice == "SRv6 Policy":
        src = colp1.text_input("Src", "PE1")
        dst = colp2.text_input("Dst", "PE2")
        pol = colp3.text_input("Policy", "SRv6-Policy-1")
        if st.button("➕ Insertar preset SRv6"):
            sid = f"service/srv6/{pol}"
            st.session_state["nodes"][sid] = {"id": sid, "type": "service-instance-type",
                "parameters_key": "service-instance-parameter",
                "parameters": {"service": "srv6-te", "instance-name": pol}}
            srpm = f"srpm/{src}-{dst}"
            st.session_state["nodes"][srpm] = {"id": srpm, "type": "preset:srpm-latency",
                "parameters_key": "preset:parameters",
                "parameters": {"src": src, "dst": dst, "policy": pol, "threshold_ms": 200}}
            st.session_state["dependencies"] += [
                {"src_id": sid, "dst_id": srpm, "dependency-type": "supporting"},
            ]
            st.success("Preset SRv6 agregado.")

    if preset_choice == "BFD Session":
        dev = colp1.text_input("Device", "PE1")
        nei = colp2.text_input("Neighbor", "PE2")
        intf = colp3.text_input("Interface", "Tunnel0")
        if st.button("➕ Insertar preset BFD"):
            nid = f"bfd/{dev}-{nei}"
            st.session_state["nodes"][nid] = {"id": nid, "type": "preset:bfd-session",
                "parameters_key": "preset:parameters",
                "parameters": {"device": dev, "neighbor": nei, "intf": intf}}
            st.success("Preset BFD agregado.")

    if preset_choice == "SR‑PM Latency":
        src = colp1.text_input("Src", "PE1")
        dst = colp2.text_input("Dst", "PE2")
        pol = colp3.text_input("Policy", "SRv6-Policy-1")
        thr = colp1.number_input("Threshold (ms)", 1, 10000, 200)
        if st.button("➕ Insertar preset SR‑PM"):
            nid = f"srpm/{src}-{dst}"
            st.session_state["nodes"][nid] = {"id": nid, "type": "preset:srpm-latency",
                "parameters_key": "preset:parameters",
                "parameters": {"src": src, "dst": dst, "policy": pol, "threshold_ms": int(thr)}}
            st.success("Preset SR‑PM agregado.")

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
    st.subheader("🧪 Validación (estructural y de parámetros)")
    # Construir grafo para validar
    G = nx.DiGraph()
    for node_id, node in st.session_state["nodes"].items():
        G.add_node(node_id, type=node["type"], pk=node["parameters_key"], params=node["parameters"])
    for d in st.session_state["dependencies"]:
        if d["src_id"] in G.nodes and d["dst_id"] in G.nodes:
            G.add_edge(d["src_id"], d["dst_id"], dep=d["dependency-type"])

    issues = []
    # 0) Referencias a nodos inexistentes
    for d in st.session_state["dependencies"]:
        if d["src_id"] not in G.nodes or d["dst_id"] not in G.nodes:
            issues.append(("error", f"Dependencia con nodo inexistente: {d}"))

    # 1) Nodos aislados
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

    # 3) Validación básica de parámetros por tipo conocido
    for n, data in G.nodes(data=True):
        t = data.get("type", "")
        pk = data.get("pk", "")
        params = data.get("params", {})
        if t in PARAM_RULES:
            rule = PARAM_RULES[t]
            expected_pk = rule["params_key"]
            if pk != expected_pk:
                issues.append(("warning", f"Nodo '{n}': parameters_key '{pk}' no coincide con '{expected_pk}' para tipo '{t}'."))
            missing = [k for k in rule["required"] if k not in params]
            if missing:
                issues.append(("error", f"Nodo '{n}': faltan claves requeridas {missing} en parámetros para tipo '{t}'."))

    if issues:
        for lvl, msg in issues:
            if lvl == "error":
                st.error(msg)
            elif lvl == "warning":
                st.warning(msg)
    else:
        st.success("Sin problemas detectados. El grafo es acíclico y los parámetros básicos parecen correctos.")

    # Validación opcional con yangson (si está instalado y se suben módulos)
    st.markdown("#### ✅ Validación YANG estricta (opcional)")
    st.caption("Subí los módulos `.yang` y una `yang-library.json` (por ejemplo, los del RFC 9418). Intentaré validar la instancia con **yangson** si está instalado.")
    yang_files = st.file_uploader("Módulos YANG (.yang) — podés subir varios", type=["yang"], accept_multiple_files=True)
    yang_lib = st.file_uploader("yang-library.json", type=["json"])
    if st.button("Ejecutar validación YANG (si es posible)"):
        try:
            import tempfile, os
            from yangson.datamodel import DataModel
            from yangson.context import Context
            from yangson.instance import Instance
            # Guardar archivos a un dir temp
            with tempfile.TemporaryDirectory() as td:
                mod_dir = os.path.join(td, "mods")
                os.makedirs(mod_dir, exist_ok=True)
                for f in yang_files or []:
                    open(os.path.join(mod_dir, f.name), "wb").write(f.read())
                if yang_lib is None:
                    st.warning("Falta 'yang-library.json'. No se puede validar.")
                else:
                    yl = json.loads(yang_lib.read())
                    # Crear DataModel
                    dm = DataModel.from_yang_library(yl, [mod_dir])
                    ctx = Context(dm)
                    # Instancia JSON a validar
                    instance_json = build_json()
                    inst = Instance(ctx, instance_json)
                    st.success("Validación YANG completada sin errores con yangson.")
        except ModuleNotFoundError:
            st.info("No encontré el módulo 'yangson'. Instalalo con: `pip install yangson`")
        except Exception as e:
            st.error(f"Error al validar con yangson: {e}")

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
        y0 = 1.02
        for i, (t, c) in enumerate(COLOR_MAP.items()):
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

**Presets incluidos**  
- L2VPN P2P, L3VPN, SR‑MPLS LSP, SRv6 Policy, BFD, SR‑PM Latency.

**Validación**  
- **Estructural**: nodos inexistentes, nodos aislados, ciclos (debe ser **DAG**).  
- **Parámetros**: para tipos RFC conocidos, revisa claves requeridas y `parameters_key`.  
- **YANG estricta (opcional)**: subí módulos `.yang` + `yang-library.json` y, si tenés **yangson** instalado (`pip install yangson`), valida contra los modelos reales.

**Exportación**  
- JSON (RFC 9418), Graphviz `.dot`, PNG del grafo.
""")

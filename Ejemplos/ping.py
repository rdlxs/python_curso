# ping_dashboard.py  (Windows/Linux/macOS) con Auto-Refresh estable
import platform, re, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import pandas as pd
import streamlit as st

# -----------------------------
# Ping helpers
# -----------------------------
def build_ping(ip: str) -> list[str]:
    if platform.system() == "Windows":
        return ["ping", "-n", "1", "-w", "1000", ip]
    else:
        return ["ping", "-c", "1", "-W", "1", ip]

_RTT_PATTERNS = [
    re.compile(r"(?:time)[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE),
    re.compile(r"(?:tiempo)[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE),
]
_RTT_SUMMARY = re.compile(r"(?:Media|Promedio|Average)\s*=\s*([0-9]+)\s*ms", re.IGNORECASE)

def parse_rtt_ms(ping_output: str) -> float | None:
    if not ping_output:
        return None
    for pat in _RTT_PATTERNS:
        m = pat.search(ping_output)
        if m:
            try: return float(m.group(1))
            except ValueError: pass
    m = _RTT_SUMMARY.search(ping_output)
    if m:
        try: return float(m.group(1))
        except ValueError: return None
    return None

def ping_once(ip: str) -> dict:
    try:
        p = subprocess.run(build_ping(ip), capture_output=True, text=True, timeout=3)
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        out = ""
    rtt = parse_rtt_ms(out)
    alive = bool(re.search(r"\bttl\s*=\s*[0-9]+", out, re.IGNORECASE)) or (rtt is not None)
    return {"ip": ip, "alive": alive, "rtt_ms": rtt}

def ping_many(ips):
    results = []
    max_workers = min(32, len(ips) or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(ping_once, i) for i in ips]
        for fut in as_completed(futures):
            results.append(fut.result())
    return results

# -----------------------------
# Streamlit UI + Estado
# -----------------------------
st.set_page_config(page_title="Ping Dashboard", layout="wide")
st.title("Ping dashboard — ICMP simple (con auto-refresh)")

# Estado global
if "stats" not in st.session_state:
    st.session_state.stats = {}  # { ip: {"sent":0,"recv":0,"last_rtt":None,"last_alive":False,"last_checked":""} }
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = 0.0
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False
if "interval" not in st.session_state:
    st.session_state.interval = 3

with st.sidebar:
    st.header("Control")
    st.checkbox("Auto-refresh", key="auto_refresh")
    st.slider("Intervalo (seg)", min_value=1, max_value=30, key="interval")
    if st.button("Reset contadores"):
        st.session_state.stats = {}
        st.success("Contadores reseteados.")

ips_text = st.text_area("IPs/hosts (una por línea)", "8.8.8.8\n1.1.1.1", height=120)

colA, colB = st.columns(2)
with colA:
    run_once = st.button("Ejecutar ahora")
with colB:
    st.caption("Activá **Auto-refresh** en la barra lateral para ver los contadores en tiempo real.")

def update_stats(measurements: list[dict]):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in measurements:
        ip = row["ip"]
        alive = bool(row["alive"])
        rtt = row["rtt_ms"]
        s = st.session_state.stats.get(ip, {"sent": 0, "recv": 0, "last_rtt": None, "last_alive": False, "last_checked": ""})
        s["sent"] += 1
        if alive:
            s["recv"] += 1
            s["last_rtt"] = rtt
        s["last_alive"] = alive
        s["last_checked"] = now
        st.session_state.stats[ip] = s

def build_table(ips: list[str]) -> pd.DataFrame:
    rows = []
    for ip in ips:
        s = st.session_state.stats.get(ip, {"sent": 0, "recv": 0, "last_rtt": None, "last_alive": False, "last_checked": ""})
        sent = s["sent"]; recv = s["recv"]
        loss_pct = round((1 - (recv / sent)) * 100, 2) if sent > 0 else None
        rows.append({
            "IP/Host": ip,
            "Estado": "UP" if s["last_alive"] else "DOWN",
            "RTT último (ms)": round(s["last_rtt"], 2) if isinstance(s["last_rtt"], (int, float)) else None,
            "ICMP enviados": sent,
            "ICMP recibidos": recv,
            "Pérdida (%)": loss_pct,
            "Comprobado": s["last_checked"],
        })
    return pd.DataFrame(rows)

def do_measurement(ips: list[str]):
    if not ips: 
        return
    data = ping_many(ips)
    update_stats(data)

# Normalizamos listado de IPs
ips = [l.strip() for l in ips_text.splitlines() if l.strip()]

# Disparo manual
if run_once:
    do_measurement(ips)

# 🔁 Disparo automático (estable con session_state)
now_ts = time.time()
if st.session_state.auto_refresh and (now_ts - st.session_state.last_refresh >= st.session_state.interval):
    do_measurement(ips)
    st.session_state.last_refresh = now_ts
    st.rerun()  # Streamlit moderno

# KPIs + Tabla
df_view = build_table(ips)
up_count = int((df_view["Estado"] == "UP").sum()) if not df_view.empty else 0
down_count = int((df_view["Estado"] == "DOWN").sum()) if not df_view.empty else 0

k1, k2 = st.columns(2)
with k1: st.metric("UP", up_count)
with k2: st.metric("DOWN", down_count)

st.dataframe(
    df_view[["IP/Host", "Estado", "RTT último (ms)", "ICMP enviados", "ICMP recibidos", "Pérdida (%)", "Comprobado"]],
    height=360
)

st.caption("Nota: algunos hosts bloquean ICMP y pueden figurar DOWN. Los contadores se mantienen mientras dure la sesión.")

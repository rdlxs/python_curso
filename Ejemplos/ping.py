# ping_dashboard.py  (Windows/Linux/macOS) con Auto-Refresh, Contadores y Logs
import platform, re, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import deque
import pandas as pd
import streamlit as st

# -----------------------------
# Config
# -----------------------------
LOG_SIZE = 30  # cuántos resultados recientes guardamos por IP

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
            try:
                return float(m.group(1))
            except ValueError:
                pass
    m = _RTT_SUMMARY.search(ping_output)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
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
st.title("Ping dashboard — ICMP simple (auto-refresh + logs)")

# Estado global
if "stats" not in st.session_state:
    st.session_state.stats = {}  # { ip: {sent, recv, last_rtt, last_alive, last_checked} }
if "logs" not in st.session_state:
    st.session_state.logs = {}   # { ip: deque([ {ts, alive, rtt_ms} ], maxlen=LOG_SIZE) }
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
    if st.button("Reset contadores y logs"):
        st.session_state.stats = {}
        st.session_state.logs = {}
        st.session_state.last_refresh = 0.0
        st.success("Reinicio completo.")

# Entrada de IPs
ips_text = st.text_area("IPs/hosts (una por línea)", "8.8.8.8\n1.1.1.1", height=120)
ips = [l.strip() for l in ips_text.splitlines() if l.strip()]

# Barra de estado (countdown + progreso)
now_ts = time.time()
if st.session_state.auto_refresh and st.session_state.interval > 0:
    next_at = (st.session_state.last_refresh or now_ts) + st.session_state.interval
    remaining = max(0, int(round(next_at - now_ts)))
    elapsed = max(0.0, now_ts - (st.session_state.last_refresh or now_ts))
    frac = min(1.0, elapsed / st.session_state.interval) if st.session_state.interval else 0.0
    st.markdown(
        f"**Auto-refresh:** ON • Próximo muestreo en **{remaining}s** "
        f"(intervalo {st.session_state.interval}s)"
    )
    st.progress(int(frac * 100))
else:
    st.markdown("**Auto-refresh:** OFF")

# Botón manual
colA, colB = st.columns(2)
with colA:
    run_once = st.button("Ejecutar ahora")
with colB:
    st.caption("Tip: activá **Auto-refresh** (barra lateral) para ver contadores y logs crecer automáticamente.")

def update_stats_and_logs(measurements: list[dict]):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in measurements:
        ip = row["ip"]
        alive = bool(row["alive"])
        rtt = row["rtt_ms"]

        # Stats
        s = st.session_state.stats.get(ip, {"sent": 0, "recv": 0, "last_rtt": None, "last_alive": False, "last_checked": ""})
        s["sent"] += 1
        if alive:
            s["recv"] += 1
            s["last_rtt"] = rtt
        s["last_alive"] = alive
        s["last_checked"] = now
        st.session_state.stats[ip] = s

        # Logs
        if ip not in st.session_state.logs:
            st.session_state.logs[ip] = deque(maxlen=LOG_SIZE)
        st.session_state.logs[ip].append({
            "Timestamp": now,
            "Estado": "UP" if alive else "DOWN",
            "RTT (ms)": round(rtt, 2) if isinstance(rtt, (int, float)) else None,
        })

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
    update_stats_and_logs(data)

# Disparo manual
if run_once:
    do_measurement(ips)

# 🔁 Disparo automático
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

# 🔎 Logs por host (expanders)
st.subheader("Logs recientes por host")
if not ips:
    st.info("Ingresá al menos una IP/host para ver logs.")
else:
    for ip in ips:
        log = list(st.session_state.logs.get(ip, []))
        with st.expander(f"{ip} — últimos {LOG_SIZE} resultados", expanded=False):
            if log:
                log_df = pd.DataFrame(log)
                st.dataframe(log_df, height=220, use_container_width=True)
            else:
                st.write("Sin datos aún para este host.")

st.caption("Nota: algunos hosts bloquean ICMP y pueden figurar DOWN. Los contadores y logs se mantienen mientras dure la sesión.")

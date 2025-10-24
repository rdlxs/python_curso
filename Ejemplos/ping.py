import streamlit as st
import subprocess
import platform
import time
import threading
import re
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

# --------------------------
# Función de ping
# --------------------------
def ping_once(host: str, timeout_ms: int = 1000):
    is_win = platform.system().lower() == "windows"
    cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host] if is_win else ["ping", "-c", "1", "-W", str(timeout_ms // 1000), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=(timeout_ms / 1000) + 1)
        out = proc.stdout or ""
        up = proc.returncode == 0 and ("TTL=" in out or "ttl=" in out)
        latency = None
        if up:
            match = re.search(r"(?:time|tiempo)[=<]?\s*(\d+(?:\.\d+)?)\s*ms", out, re.IGNORECASE)
            if match:
                latency = float(match.group(1))
        return up, latency
    except Exception:
        return False, None


# --------------------------
# Estado inicial
# --------------------------
def ensure_state():
    if "monitoring" not in st.session_state:
        st.session_state.monitoring = False
    if "interval" not in st.session_state:
        st.session_state.interval = 2
    if "results" not in st.session_state:
        st.session_state.results = {}
    if "ip_list" not in st.session_state:
        st.session_state.ip_list = []


def init_results(ip_list):
    st.session_state.results = {
        ip: {"status": "⏳", "sent": 0, "received": 0, "loss": 0, "last_latency": None, "avg_latency": None}
        for ip in ip_list
    }


# --------------------------
# Hilo de monitoreo
# --------------------------
def monitor_loop(stop_flag):
    while not stop_flag[0]:
        with ThreadPoolExecutor(max_workers=32) as executor:
            futures = {ip: executor.submit(ping_once, ip) for ip in st.session_state.ip_list}
            for ip, fut in futures.items():
                up, latency = fut.result()
                r = st.session_state.results[ip]
                r["sent"] += 1
                if up:
                    r["received"] += 1
                    r["status"] = "🟢 UP"
                    r["last_latency"] = latency
                    if latency is not None:
                        if r["avg_latency"] is None:
                            r["avg_latency"] = latency
                        else:
                            r["avg_latency"] = round(float(r["avg_latency"]) * 0.7 + float(latency) * 0.3, 2)
                else:
                    r["loss"] += 1
                    r["status"] = "🔴 DOWN"
                    r["last_latency"] = None
        time.sleep(st.session_state.interval)


# --------------------------
# Interfaz Streamlit
# --------------------------
st.set_page_config(page_title="Multi Ping Dashboard", layout="wide")
st.title("🔎 Multi Ping Dashboard")

ensure_state()

with st.sidebar:
    st.header("Configuración")
    ip_input = st.text_area("IPs (una por línea)", "8.8.8.8\n1.1.1.1")
    st.session_state.interval = st.number_input("Intervalo (segundos)", 1, 60, st.session_state.interval)
    col1, col2 = st.columns(2)

    if col1.button("▶ Iniciar"):
        st.session_state.ip_list = [x.strip() for x in ip_input.splitlines() if x.strip()]
        init_results(st.session_state.ip_list)
        st.session_state.monitoring = True
        st.session_state._stop_flag = [False]
        threading.Thread(target=monitor_loop, args=(st.session_state._stop_flag,), daemon=True).start()

    if col2.button("⏹ Detener"):
        if st.session_state.monitoring:
            st.session_state._stop_flag[0] = True
            st.session_state.monitoring = False


# ✅ Refresco visual sin bloquear (compatible con todas las versiones)
if st.session_state.monitoring:
    # Si la versión actual tiene st.autorefresh, úsala
    if hasattr(st, "autorefresh"):
        st.autorefresh(interval=st.session_state.interval * 1000, key="refresh_key")
    else:
        # Fallback universal: usa un marcador invisible para forzar el rerun
        # sin depender de atributos experimentales
        time.sleep(st.session_state.interval)
        st.experimental_set_query_params(_=time.time())


# --------------------------
# Render principal
# --------------------------
if st.session_state.results:
    df = pd.DataFrame.from_dict(st.session_state.results, orient="index")
    df.index.name = "IP"
    df = df.reset_index()[["IP", "status", "sent", "received", "loss", "last_latency", "avg_latency"]]
    df.columns = ["IP", "Estado", "Enviados", "Recibidos", "Perdidos", "Latencia última (ms)", "Latencia prom (ms)"]
    st.dataframe(df, use_container_width=True, height=400)
else:
    st.info("Cargá IPs y presioná **Iniciar** para comenzar el monitoreo.")

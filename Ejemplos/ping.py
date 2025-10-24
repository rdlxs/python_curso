import streamlit as st
import subprocess
import platform
import time
import threading

def ping_host(host):
    """Ejecuta un ping y devuelve True/False + latencia."""
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "1", host]
    try:
        output = subprocess.check_output(command, universal_newlines=True)
        if "TTL=" in output:
            latency = output.split("time=")[1].split("ms")[0].strip()
            return True, latency
        else:
            return False, None
    except subprocess.CalledProcessError:
        return False, None

def run_pings(ip_list, results):
    while True:
        for ip in ip_list:
            up, latency = ping_host(ip)
            results[ip]["status"] = "🟢 UP" if up else "🔴 DOWN"
            if up:
                results[ip]["sent"] += 1
                results[ip]["received"] += 1
                results[ip]["loss"] = 0
                results[ip]["latency"] = latency
            else:
                results[ip]["sent"] += 1
                results[ip]["loss"] += 1
        time.sleep(3)

st.title("🔎 Multi Ping Dashboard")

ip_input = st.text_area("Lista de IPs (una por línea)", "8.8.8.8\n1.1.1.1")
ip_list = [x.strip() for x in ip_input.splitlines() if x.strip()]

if st.button("Iniciar monitoreo"):
    results = {ip: {"status": "⏳", "sent": 0, "received": 0, "loss": 0, "latency": "-"} for ip in ip_list}
    thread = threading.Thread(target=run_pings, args=(ip_list, results), daemon=True)
    thread.start()

    placeholder = st.empty()
    while True:
        data = [
            [ip, r["status"], r["sent"], r["received"], r["loss"], r["latency"]]
            for ip, r in results.items()
        ]
        placeholder.table(
            data=[["IP", "Estado", "Enviados", "Recibidos", "Perdidos", "Latencia (ms)"]] + data
        )
        time.sleep(2)

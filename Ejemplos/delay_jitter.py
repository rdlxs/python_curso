import argparse
import csv
import logging
import os
import socket
import struct
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from statistics import mean

from flask import Flask, jsonify, render_template_string

# ============================================================
# ICMP
# ============================================================

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0
PAYLOAD_SIZE = 32

# ============================================================
# Estado global compartido entre el medidor y Flask
# ============================================================

samples = deque()
samples_lock = threading.Lock()
stop_event = threading.Event()

app = Flask(__name__)

TARGET = ""
TARGET_IP = ""
INTERVAL = 0.25
TIMEOUT = 1.0
MAX_POINTS = 600
CSV_FILE = ""


def internet_checksum(data: bytes) -> int:
    """Calcula el checksum de 16 bits usado por ICMP."""
    if len(data) % 2:
        data += b"\x00"

    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


class RawIcmpPinger:
    """
    Envía ICMP Echo Request usando un socket RAW y mide el RTT con
    time.perf_counter_ns(), evitando parsear la salida de ping.exe.
    """

    def __init__(self, target: str, timeout: float):
        self.target = target
        self.target_ip = socket.gethostbyname(target)
        self.timeout = timeout
        self.identifier = os.getpid() & 0xFFFF
        self.sequence = 0

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_RAW,
            socket.IPPROTO_ICMP,
        )

    def close(self):
        self.sock.close()

    def _build_packet(self, sequence: int) -> bytes:
        # Header ICMP sin checksum para poder calcularlo después.
        header = struct.pack(
            "!BBHHH",
            ICMP_ECHO_REQUEST,
            0,                  # code
            0,                  # checksum temporal
            self.identifier,
            sequence,
        )

        # Payload de 32 bytes. No usamos el contenido para medir tiempo;
        # el RTT se calcula exclusivamente con perf_counter_ns().
        payload = (
            b"ONTMON"
            + struct.pack("!H", sequence)
            + os.urandom(PAYLOAD_SIZE - 8)
        )

        checksum = internet_checksum(header + payload)

        header = struct.pack(
            "!BBHHH",
            ICMP_ECHO_REQUEST,
            0,
            checksum,
            self.identifier,
            sequence,
        )

        return header + payload

    def ping(self):
        """
        Devuelve RTT en milisegundos con decimales.
        Devuelve None si vence el timeout.
        """
        self.sequence = (self.sequence + 1) & 0xFFFF
        sequence = self.sequence
        packet = self._build_packet(sequence)

        # El reloj empieza lo más cerca posible del envío real.
        start_ns = time.perf_counter_ns()
        self.sock.sendto(packet, (self.target_ip, 0))

        deadline_ns = start_ns + int(self.timeout * 1_000_000_000)

        while True:
            remaining_ns = deadline_ns - time.perf_counter_ns()
            if remaining_ns <= 0:
                return None

            self.sock.settimeout(remaining_ns / 1_000_000_000)

            try:
                received_packet, address = self.sock.recvfrom(65535)
                end_ns = time.perf_counter_ns()
            except socket.timeout:
                return None

            if len(received_packet) < 8:
                continue

            # Los sockets RAW IPv4 normalmente entregan también el header IP.
            # Detectamos si está presente y encontramos dónde comienza ICMP.
            if (received_packet[0] >> 4) == 4 and len(received_packet) >= 20:
                ihl = (received_packet[0] & 0x0F) * 4
                if len(received_packet) < ihl + 8:
                    continue
                icmp = received_packet[ihl:]
            else:
                icmp = received_packet

            icmp_type, code, _, packet_id, packet_seq = struct.unpack(
                "!BBHHH",
                icmp[:8],
            )

            # Ignoramos cualquier ICMP que no sea exactamente nuestra respuesta.
            if (
                icmp_type == ICMP_ECHO_REPLY
                and code == 0
                and packet_id == self.identifier
                and packet_seq == sequence
                and address[0] == self.target_ip
            ):
                return (end_ns - start_ns) / 1_000_000.0


def save_sample(sample: dict):
    """Agrega una muestra al CSV de la sesión."""
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                sample["seq"],
                sample["timestamp"],
                "" if sample["rtt_ms"] is None else sample["rtt_ms"],
                "" if sample["jitter_ms"] is None else sample["jitter_ms"],
                "TIMEOUT" if sample["rtt_ms"] is None else "OK",
            ]
        )


def measurement_loop():
    """Loop de medición ejecutado en un thread separado de Flask."""
    try:
        pinger = RawIcmpPinger(TARGET, TIMEOUT)
    except PermissionError:
        print("\nERROR: no hay permisos para abrir el socket ICMP RAW.")
        print("Windows: abrí PowerShell/CMD como Administrador.")
        print("Linux/macOS: ejecutá con sudo.\n")
        stop_event.set()
        return
    except OSError as exc:
        print(f"\nERROR al crear el socket ICMP RAW: {exc}\n")
        stop_event.set()
        return

    previous_rtt = None
    sample_number = 0
    next_run = time.perf_counter()

    try:
        while not stop_event.is_set():
            sample_number += 1
            rtt = pinger.ping()

            if rtt is None:
                # Tras una pérdida reseteamos la referencia para no calcular
                # jitter entre dos muestras separadas por un timeout.
                jitter = None
                previous_rtt = None
            else:
                # Jitter instantáneo: variación absoluta entre RTT consecutivos.
                jitter = (
                    abs(rtt - previous_rtt)
                    if previous_rtt is not None
                    else None
                )
                previous_rtt = rtt

            sample = {
                "seq": sample_number,
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                "rtt_ms": None if rtt is None else round(rtt, 6),
                "jitter_ms": None if jitter is None else round(jitter, 6),
            }

            # La web sólo conserva una ventana móvil.
            with samples_lock:
                samples.append(sample)
                while len(samples) > MAX_POINTS:
                    samples.popleft()

            # El CSV conserva toda la sesión.
            save_sample(sample)

            if rtt is None:
                print(f"{sample_number:06d}  TIMEOUT")
            else:
                jitter_text = "-" if jitter is None else f"{jitter:.3f} ms"
                print(
                    f"{sample_number:06d}  "
                    f"RTT={rtt:.3f} ms  "
                    f"Jitter={jitter_text}"
                )

            # Intentamos mantener constante el período entre comienzos de muestra.
            next_run += INTERVAL
            sleep_time = next_run - time.perf_counter()

            if sleep_time > 0:
                stop_event.wait(sleep_time)
            else:
                # Si una medición tardó más que el intervalo, evitamos acumular drift.
                next_run = time.perf_counter()

    finally:
        pinger.close()


def current_stats(data):
    """Estadísticas de la ventana actualmente visible en el dashboard."""
    sent = len(data)
    rtts = [item["rtt_ms"] for item in data if item["rtt_ms"] is not None]
    jitters = [
        item["jitter_ms"]
        for item in data
        if item["jitter_ms"] is not None
    ]

    if sent == 0:
        return {
            "sent": 0,
            "received": 0,
            "loss_pct": 0.0,
            "last_rtt": None,
            "min_rtt": None,
            "avg_rtt": None,
            "max_rtt": None,
            "avg_jitter": None,
            "max_jitter": None,
        }

    return {
        "sent": sent,
        "received": len(rtts),
        "loss_pct": round((sent - len(rtts)) * 100 / sent, 3),
        "last_rtt": None if not rtts else rtts[-1],
        "min_rtt": None if not rtts else round(min(rtts), 6),
        "avg_rtt": None if not rtts else round(mean(rtts), 6),
        "max_rtt": None if not rtts else round(max(rtts), 6),
        "avg_jitter": None if not jitters else round(mean(jitters), 6),
        "max_jitter": None if not jitters else round(max(jitters), 6),
    }


HTML = r"""
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ONT Latency Monitor</title>

    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"></script>

    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #101418;
            color: #e8edf2;
        }
        .container {
            max-width: 1500px;
            margin: auto;
            padding: 20px;
        }
        h1 { margin-bottom: 5px; }
        .subtitle {
            color: #9da8b3;
            margin-bottom: 20px;
        }
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }
        .card {
            background: #1a2128;
            border-radius: 10px;
            padding: 15px;
        }
        .label {
            font-size: 13px;
            color: #98a3ad;
        }
        .value {
            font-size: 25px;
            margin-top: 6px;
            font-weight: bold;
        }
        .chart-box {
            background: #1a2128;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 18px;
            height: 350px;
        }
        .ok { color: #8ee6a0; }
        .bad { color: #ff8585; }
    </style>
</head>
<body>
<div class="container">
    <h1>ONT Latency Monitor</h1>
    <div class="subtitle">
        Destino: <strong>{{ target }}</strong> ({{ target_ip }}) |
        intervalo: {{ interval }} s |
        ventana: {{ max_points }} muestras
    </div>

    <div class="cards">
        <div class="card"><div class="label">RTT actual</div><div class="value" id="lastRtt">-</div></div>
        <div class="card"><div class="label">RTT mínimo</div><div class="value" id="minRtt">-</div></div>
        <div class="card"><div class="label">RTT promedio</div><div class="value" id="avgRtt">-</div></div>
        <div class="card"><div class="label">RTT máximo</div><div class="value" id="maxRtt">-</div></div>
        <div class="card"><div class="label">Jitter promedio</div><div class="value" id="avgJitter">-</div></div>
        <div class="card"><div class="label">Jitter máximo</div><div class="value" id="maxJitter">-</div></div>
        <div class="card"><div class="label">Packet loss</div><div class="value" id="loss">-</div></div>
    </div>

    <div class="chart-box"><canvas id="latencyChart"></canvas></div>
    <div class="chart-box"><canvas id="jitterChart"></canvas></div>
</div>

<script>
const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    normalized: true,
    parsing: false,
    spanGaps: false,
    scales: {
        x: {
            type: "linear",
            ticks: { maxTicksLimit: 12 },
            title: { display: true, text: "Muestra" }
        },
        y: {
            beginAtZero: true,
            title: { display: true, text: "ms" }
        }
    }
};

const latencyChart = new Chart(document.getElementById("latencyChart"), {
    type: "line",
    data: {
        datasets: [{
            label: "Latencia RTT (ms)",
            data: [],
            borderWidth: 1.5,
            pointRadius: 1
        }]
    },
    options: structuredClone(commonOptions)
});

const jitterChart = new Chart(document.getElementById("jitterChart"), {
    type: "line",
    data: {
        datasets: [{
            label: "Jitter instantáneo (ms)",
            data: [],
            borderWidth: 1.5,
            pointRadius: 1
        }]
    },
    options: structuredClone(commonOptions)
});

function fmt(value) {
    if (value === null || value === undefined) return "-";
    if (value < 1) return value.toFixed(3) + " ms";
    return value.toFixed(2) + " ms";
}

async function refresh() {
    try {
        const response = await fetch("/api/data", { cache: "no-store" });
        const payload = await response.json();

        // Incluimos null en los timeouts para que el gráfico muestre un hueco.
        latencyChart.data.datasets[0].data = payload.samples.map(item => ({
            x: item.seq,
            y: item.rtt_ms
        }));

        jitterChart.data.datasets[0].data = payload.samples.map(item => ({
            x: item.seq,
            y: item.jitter_ms
        }));

        latencyChart.update("none");
        jitterChart.update("none");

        const s = payload.stats;
        document.getElementById("lastRtt").textContent = fmt(s.last_rtt);
        document.getElementById("minRtt").textContent = fmt(s.min_rtt);
        document.getElementById("avgRtt").textContent = fmt(s.avg_rtt);
        document.getElementById("maxRtt").textContent = fmt(s.max_rtt);
        document.getElementById("avgJitter").textContent = fmt(s.avg_jitter);
        document.getElementById("maxJitter").textContent = fmt(s.max_jitter);

        const loss = document.getElementById("loss");
        loss.textContent = s.loss_pct.toFixed(2) + " %";
        loss.className = "value " + (s.loss_pct === 0 ? "ok" : "bad");
    } catch (error) {
        console.error("No se pudo actualizar el dashboard:", error);
    }
}

refresh();
setInterval(refresh, 500);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        HTML,
        target=TARGET,
        target_ip=TARGET_IP,
        interval=INTERVAL,
        max_points=MAX_POINTS,
    )


@app.route("/api/data")
def api_data():
    with samples_lock:
        data = list(samples)

    return jsonify({
        "samples": data,
        "stats": current_stats(data),
    })


def create_csv():
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "seq",
            "timestamp",
            "rtt_ms",
            "jitter_ms",
            "status",
        ])


def main():
    global TARGET, TARGET_IP, INTERVAL, TIMEOUT, MAX_POINTS, CSV_FILE

    parser = argparse.ArgumentParser(
        description="Monitor preciso de latencia y jitter ICMP hacia una ONT."
    )
    parser.add_argument("target", help="IP o hostname de la ONT")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.25,
        help="Intervalo entre muestras en segundos. Default: 0.25",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Timeout ICMP en segundos. Default: 1.0",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=600,
        help="Muestras visibles en la web. Default: 600",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Puerto web local. Default: 5000",
    )

    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval debe ser mayor que 0")
    if args.timeout <= 0:
        parser.error("--timeout debe ser mayor que 0")
    if args.points < 10:
        parser.error("--points debe ser al menos 10")

    TARGET = args.target
    TARGET_IP = socket.gethostbyname(TARGET)
    INTERVAL = args.interval
    TIMEOUT = args.timeout
    MAX_POINTS = args.points

    stop_event.clear()
    with samples_lock:
        samples.clear()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    CSV_FILE = f"ont_latency_{timestamp}.csv"
    create_csv()

    # Evita que Flask ensucie la consola con un GET /api/data cada 500 ms.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    print("=" * 70)
    print("ONT LATENCY MONITOR")
    print("=" * 70)
    print(f"Destino       : {TARGET} ({TARGET_IP})")
    print(f"Intervalo     : {INTERVAL} s")
    print(f"Timeout       : {TIMEOUT} s")
    print(f"CSV           : {CSV_FILE}")
    print(f"Dashboard     : http://127.0.0.1:{args.port}")
    print("=" * 70)

    worker = threading.Thread(
        target=measurement_loop,
        daemon=True,
        name="icmp-monitor",
    )
    worker.start()

    def open_dashboard():
        if not stop_event.is_set():
            webbrowser.open(f"http://127.0.0.1:{args.port}")

    threading.Timer(1.0, open_dashboard).start()

    try:
        app.run(
            host="127.0.0.1",
            port=args.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
MultiPing minimal: pingeos concurrentes con asyncio + subprocess.
Imprime tabla en consola con latencia promedio, recuento y pérdida.
Uso: python3 multi_ping.py hosts.txt
hosts.txt = una IP/host por línea (comentarios con #)
"""
import asyncio
import sys
import platform
import time
from collections import deque, defaultdict

DEFAULT_INTERVAL = 2.0  # segundos entre pings por host
SAMPLE_WINDOW = 10      # cantidad de muestras para calcular promedio

IS_WINDOWS = platform.system() == "Windows"

def make_ping_cmd(host):
    if IS_WINDOWS:
        # -n 1 (uno), -w timeout(ms)
        return ["ping", "-n", "1", "-w", "1000", host]
    else:
        # -c 1 (uno), -W timeout(s)
        return ["ping", "-c", "1", "-W", "1", host]

def parse_latency(output: str) -> float | None:
    out = output.lower()
    # Linux example: "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=14.1 ms"
    # Windows example: "Approximate round trip times in milli-seconds: Minimum = 14ms, Maximum = 14ms, Average = 14ms"
    if "time=" in out:
        try:
            # take substring after time= and up to ' ms'
            part = out.split("time=")[1].split()[0]
            # remove trailing 'ms' if present
            part = part.replace("ms", "")
            return float(part)
        except Exception:
            return None
    if "average" in out and "ms" in out:
        try:
            avg = out.split("average =")[-1].strip().replace("ms","").replace("msec","").strip()
            return float(avg)
        except Exception:
            return None
    return None

class HostStats:
    def __init__(self):
        self.samples = deque(maxlen=SAMPLE_WINDOW)
        self.sent = 0
        self.recv = 0
    def add(self, latency):
        self.sent += 1
        if latency is None:
            # timeout / lost
            self.samples.append(None)
        else:
            self.recv += 1
            self.samples.append(latency)
    def loss_pct(self):
        if self.sent == 0: return 0.0
        return 100.0 * (self.sent - self.recv) / self.sent
    def avg_latency(self):
        vals = [v for v in self.samples if v is not None]
        return sum(vals)/len(vals) if vals else None
    def last(self):
        if not self.samples: return None
        return self.samples[-1]

async def ping_host_loop(host, stats: HostStats, interval=DEFAULT_INTERVAL):
    cmd = make_ping_cmd(host)
    while True:
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            out = (stdout or b"").decode(errors="ignore") + (stderr or b"").decode(errors="ignore")
            latency = parse_latency(out)
        except Exception:
            latency = None
        stats.add(latency)
        # sleep remainder
        elapsed = time.time() - start
        await asyncio.sleep(max(0, interval - elapsed))

def format_val(lat):
    if lat is None: return "----"
    return f"{lat:.1f} ms"

async def main(hosts, interval=DEFAULT_INTERVAL):
    stats_map = {h: HostStats() for h in hosts}
    tasks = [asyncio.create_task(ping_host_loop(h, stats_map[h], interval)) for h in hosts]

    try:
        while True:
            # clear screen
            print("\033[H\033[J", end="")  # funciona en la mayoría de terminales
            print(f"MultiPing - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'Host':30} {'Last':8} {'Avg':8} {'Sent':5} {'Recv':5} {'Loss%':6}")
            print("-"*70)
            for h in hosts:
                s = stats_map[h]
                last = format_val(s.last())
                avg = format_val(s.avg_latency()) if s.avg_latency() is not None else "----"
                print(f"{h:30} {last:8} {avg:8} {s.sent:5d} {s.recv:5d} {s.loss_pct():6.1f}")
            await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("\nStopped.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 multi_ping.py hosts.txt")
        sys.exit(1)
    hostsfile = sys.argv[1]
    with open(hostsfile, "r", encoding="utf-8") as f:
        hosts = [line.strip().split("#",1)[0].strip() for line in f if line.strip() and not line.strip().startswith("#")]
    asyncio.run(main(hosts))

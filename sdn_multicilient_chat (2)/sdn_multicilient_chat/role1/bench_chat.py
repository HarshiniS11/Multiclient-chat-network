#!/usr/bin/env python3
"""Performance benchmark for the chat server (standard library only).

Runs from any host that can reach the server, so it works inside Mininet:
    h2 python3 tools/bench_chat.py --host 10.0.0.1 --port 5000 --label baseline --csv evidence/bench.csv

Tests
  connect  N clients connect + register at the same time    -> setup time per client
  latency  PING round-trip and PRIVMSG delivery latency      -> min/mean/p50/p95/p99/max (ms)
  fanout   1 sender -> room of N-1 receivers                 -> deliveries/s and message loss

Do not run with a server that has CHAT_RATE_LIMIT set, or the fanout test will be throttled.
"""
import argparse
import csv
import os
import random
import socket
import statistics
import sys
import threading
import time


class Conn:
    def __init__(self, host, port, timeout=20):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def send(self, line):
        self.s.sendall((line + "\n").encode())

    def readline(self):
        while b"\n" not in self.buf:
            d = self.s.recv(65536)
            if not d:
                raise ConnectionError("server closed the connection")
            self.buf += d
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode()

    def request(self, line):
        """Send a command and return its OK/ERR/PONG reply (pushes are skipped)."""
        self.send(line)
        while True:
            r = self.readline()
            if r.startswith(("OK", "ERR", "PONG")):
                return r

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def pct(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def summarise(vals):
    v = sorted(vals)
    return {"n": len(v), "min": v[0], "mean": statistics.mean(v), "p50": pct(v, 50),
            "p95": pct(v, 95), "p99": pct(v, 99), "max": v[-1]}


class Report:
    def __init__(self, label, csv_path):
        self.label, self.csv_path = label, csv_path
        self.rows = []

    def add(self, metric, value, unit=""):
        self.rows.append((metric, value, unit))
        shown = f"{value:.3f}" if isinstance(value, float) else str(value)
        print(f"  {metric:<34} {shown} {unit}")

    def add_stats(self, prefix, vals, unit="ms"):
        s = summarise(vals)
        for k in ("n", "min", "mean", "p50", "p95", "p99", "max"):
            self.add(f"{prefix}_{k}", s[k] if k == "n" else round(s[k], 3), "" if k == "n" else unit)

    def save(self):
        if not self.csv_path:
            return
        new = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            if new:
                w.writerow(["label", "timestamp", "metric", "value", "unit"])
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            for metric, value, unit in self.rows:
                w.writerow([self.label, ts, metric, value, unit])
        print(f"\nresults appended to {self.csv_path} (label '{self.label}')")


def run_connect(args, rep, tag):
    print(f"\n[connect] {args.clients} clients registering at once")
    times, conns, errors = [], [], [0]
    lock = threading.Lock()
    barrier = threading.Barrier(args.clients)

    def worker(i):
        try:
            barrier.wait()
            t0 = time.perf_counter()
            c = Conn(args.host, args.port)
            r = c.request(f"REGISTER c{tag}x{i}")
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                if r.startswith("OK"):
                    times.append(dt)
                    conns.append(c)
                else:
                    errors[0] += 1
                    c.close()
        except Exception:
            with lock:
                errors[0] += 1

    ths = [threading.Thread(target=worker, args=(i,)) for i in range(args.clients)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    rep.add("connect_clients_ok", len(times))
    rep.add("connect_errors", errors[0])
    if times:
        rep.add_stats("connect_time", times)
    for c in conns:
        c.close()


def run_latency(args, rep, tag):
    print(f"\n[latency] {args.messages} samples, payload {args.payload} bytes")
    a, b = Conn(args.host, args.port), Conn(args.host, args.port)
    an, bn = f"la{tag}", f"lb{tag}"
    a.request(f"REGISTER {an}")
    b.request(f"REGISTER {bn}")
    pad = "x" * args.payload

    ping = []
    for _ in range(args.messages):
        t0 = time.perf_counter()
        a.request("PING")
        ping.append((time.perf_counter() - t0) * 1000)
    rep.add_stats("ping_rtt", ping)

    lat = []
    for _ in range(args.messages):
        ts = time.perf_counter_ns()
        a.send(f"PRIVMSG {bn} {ts} {pad}")
        a.readline()                              # OK sent
        line = b.readline()                       # PRIVMSG <from> <ts> <pad>
        now = time.perf_counter_ns()
        lat.append((now - int(line.split(" ", 3)[2])) / 1e6)
    rep.add_stats("privmsg_delivery", lat)
    a.close()
    b.close()


def run_fanout(args, rep, tag):
    receivers = max(1, args.clients - 1)
    total = args.messages
    print(f"\n[fanout] 1 sender -> {receivers} receivers, {total} room messages")
    room = f"bench{tag}"
    pad = "x" * args.payload
    barrier = threading.Barrier(receivers + 1)
    done_at, got_counts = [], []
    lock = threading.Lock()

    def receiver(i):
        got = 0
        try:
            c = Conn(args.host, args.port, timeout=30)
            c.request(f"REGISTER r{tag}x{i}")
            c.request(f"JOIN {room}")
            barrier.wait()
            while got < total:
                if c.readline().startswith("ROOMMSG"):
                    got += 1
            with lock:
                done_at.append(time.perf_counter())
            c.close()
        except Exception:
            pass
        finally:
            with lock:
                got_counts.append(got)

    ths = [threading.Thread(target=receiver, args=(i,)) for i in range(receivers)]
    for t in ths:
        t.start()
    s = Conn(args.host, args.port, timeout=30)
    s.request(f"REGISTER s{tag}")
    s.request(f"JOIN {room}")
    barrier.wait()

    def drain():                                  # consume OK/INFO lines
        try:
            while True:
                s.readline()
        except Exception:
            pass
    threading.Thread(target=drain, daemon=True).start()

    t0 = time.perf_counter()
    for i in range(total):
        s.send(f"ROOMMSG {room} {i} {pad}")
    for t in ths:
        t.join(timeout=60)
    end = max(done_at) if done_at else time.perf_counter()
    elapsed = end - t0
    delivered, expected = sum(got_counts), receivers * total
    rep.add("fanout_receivers", receivers)
    rep.add("fanout_messages_sent", total)
    rep.add("fanout_deliveries_expected", expected)
    rep.add("fanout_deliveries_received", delivered)
    rep.add("fanout_loss_percent", round(100 * (expected - delivered) / expected, 3), "%")
    rep.add("fanout_elapsed", round(elapsed, 3), "s")
    rep.add("fanout_throughput", round(delivered / elapsed, 1) if elapsed > 0 else 0, "deliveries/s")
    s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--clients", type=int, default=20, help="clients for connect and fanout tests")
    ap.add_argument("--messages", type=int, default=200, help="samples / messages per test")
    ap.add_argument("--payload", type=int, default=100, help="message text size in bytes (max ~900)")
    ap.add_argument("--test", choices=["all", "connect", "latency", "fanout"], default="all")
    ap.add_argument("--label", default="run", help="name for this condition, e.g. baseline or sdn-priority")
    ap.add_argument("--csv", default="", help="append results to this CSV file")
    args = ap.parse_args()
    if not 1 <= args.payload <= 900:
        sys.exit("--payload must be between 1 and 900")

    tag = "%04x" % random.randrange(65536)       # keeps usernames unique between runs
    print(f"Benchmark '{args.label}' against {args.host}:{args.port} "
          f"(clients={args.clients}, messages={args.messages}, payload={args.payload})")
    rep = Report(args.label, args.csv)
    if args.test in ("all", "connect"):
        run_connect(args, rep, tag)
    if args.test in ("all", "latency"):
        run_latency(args, rep, tag)
    if args.test in ("all", "fanout"):
        run_fanout(args, rep, tag)
    rep.save()


if __name__ == "__main__":
    main()

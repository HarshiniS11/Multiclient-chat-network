"""Multi-client TCP chat server - Project 8 (Role 1), version 1.0.

Thread-per-client design. Every client also has a writer thread fed by a
bounded queue, so a client that stops reading can never block anyone else.
See docs for the protocol. Configuration is via environment variables.
"""
import logging
import os
import queue
import re
import signal
import socket
import threading
import time

HOST = os.environ.get("CHAT_HOST", "0.0.0.0")
PORT = int(os.environ.get("CHAT_PORT", "5000"))
IDLE_TIMEOUT = float(os.environ.get("CHAT_IDLE_TIMEOUT", "300"))   # seconds
LOG_FILE = os.environ.get("CHAT_LOG", "server.log")
MAX_CLIENTS = int(os.environ.get("CHAT_MAX_CLIENTS", "200"))       # simultaneous connections
RATE_LIMIT = float(os.environ.get("CHAT_RATE_LIMIT", "0"))         # commands/second/client, 0 = off
OUTQ_MAX = int(os.environ.get("CHAT_OUTQ_MAX", "256"))             # queued lines per client
MAX_LINE = 1024
NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")

log = logging.getLogger("chat")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(), logging.FileHandler(LOG_FILE)):
        handler.setFormatter(fmt)
        log.addHandler(handler)


# ---- shared state (protected by one lock) ----
state_lock = threading.Lock()
users = {}      # username_lower -> Client
rooms = {}      # room_lower -> set of Client
active = 0      # open connections (registered or not)
stats = {"msgs_in": 0, "deliveries": 0, "start": time.time()}


class Client:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.name = None                         # set after REGISTER
        self.rooms = set()                       # rooms this client has joined
        self.outq = queue.Queue(maxsize=OUTQ_MAX)
        self.dead = False
        self.win_start = time.monotonic()        # rate-limit window
        self.win_count = 0
        self.writer = threading.Thread(target=self._writer, daemon=True)
        self.writer.start()

    # -- outgoing path: handlers only enqueue, the writer thread does the sending --
    def send(self, line):
        """Queue one protocol line. Never blocks. Safe from any thread."""
        if self.dead:
            return
        try:
            self.outq.put_nowait(line)
        except queue.Full:
            self.drop("slow consumer: output queue full")

    def _writer(self):
        while True:
            line = self.outq.get()
            if line is None:
                break
            try:
                self.conn.sendall((line + "\n").encode("utf-8"))
            except OSError:
                self.drop("write failed")
                break

    def drop(self, reason):
        """Force the connection shut; the handler thread then runs cleanup."""
        if self.dead:
            return
        self.dead = True
        log.warning("DROP %s (%s)", self.name or self.addr, reason)
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self):
        """Flush queued lines (e.g. 'OK bye'), stop the writer, close the socket."""
        try:
            self.outq.put(None, timeout=1)
        except queue.Full:
            pass
        self.writer.join(timeout=2)
        if self.writer.is_alive():
            self.drop("close with unsent data")   # shutdown unblocks the writer
        try:
            self.conn.close()
        except OSError:
            pass

    def allow(self):
        """Fixed one-second window rate limit. Always True when RATE_LIMIT is 0."""
        if RATE_LIMIT <= 0:
            return True
        now = time.monotonic()
        if now - self.win_start >= 1.0:
            self.win_start, self.win_count = now, 0
        self.win_count += 1
        return self.win_count <= RATE_LIMIT


def broadcast(targets, line):
    """Queue a line for many clients. Call this OUTSIDE state_lock."""
    for t in targets:
        t.send(line)


# ---- command handlers ----
def cmd_register(client, arg):
    if client.name is not None:
        return client.send("ERR 102 already registered")
    if not NAME_RE.match(arg):
        return client.send("ERR 103 invalid name")
    key = arg.lower()
    with state_lock:
        if key in users:
            return client.send("ERR 104 username taken")
        users[key] = client
        client.name = arg
        online = len(users)
    client.send(f"OK registered {arg}")
    log.info("REGISTER %s from %s:%s (online=%d)", arg, client.addr[0], client.addr[1], online)


def cmd_join(client, arg):
    if not NAME_RE.match(arg):
        return client.send("ERR 103 invalid name")
    room = arg.lower()
    with state_lock:
        if room in client.rooms:
            return client.send("ERR 108 already in room")
        members = rooms.setdefault(room, set())
        others = list(members)
        members.add(client)
        client.rooms.add(room)
        size = len(members)
    client.send(f"OK joined {room}")
    broadcast(others, f"INFO {client.name} joined {room}")
    log.info("JOIN %s -> %s (members=%d)", client.name, room, size)


def cmd_leave(client, arg):
    room = arg.lower()
    with state_lock:
        if room not in client.rooms:
            return client.send("ERR 105 not in that room")
        client.rooms.discard(room)
        members = rooms[room]
        members.discard(client)
        others = list(members)
        if not members:
            del rooms[room]          # empty rooms are deleted
    client.send(f"OK left {room}")
    broadcast(others, f"INFO {client.name} left {room}")
    log.info("LEAVE %s <- %s", client.name, room)


def cmd_roommsg(client, arg):
    parts = arg.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        return client.send("ERR 100 usage: ROOMMSG <room> <text>")
    room, text = parts[0].lower(), parts[1].strip()
    with state_lock:
        if room not in client.rooms:
            return client.send("ERR 105 not in that room")
        recipients = [m for m in rooms[room] if m is not client]
        stats["msgs_in"] += 1
        stats["deliveries"] += len(recipients)
    client.send("OK sent")
    broadcast(recipients, f"ROOMMSG {room} {client.name} {text}")
    log.info("ROOMMSG %s -> %s (%d chars, %d recipients)",
             client.name, room, len(text), len(recipients))


def cmd_privmsg(client, arg):
    parts = arg.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        return client.send("ERR 100 usage: PRIVMSG <user> <text>")
    target_name, text = parts[0].lower(), parts[1].strip()
    with state_lock:
        target = users.get(target_name)
        if target is not None:
            stats["msgs_in"] += 1
            stats["deliveries"] += 1
    if target is None:
        return client.send("ERR 106 user not found")
    client.send("OK sent")
    target.send(f"PRIVMSG {client.name} {text}")
    log.info("PRIVMSG %s -> %s (%d chars)", client.name, target.name, len(text))


def cmd_list(client, arg):
    what = arg.upper()
    with state_lock:
        if what == "USERS":
            names = sorted(c.name for c in users.values())
            return client.send("OK users " + ",".join(names))
        if what == "ROOMS":
            items = sorted(f"{r}({len(m)})" for r, m in rooms.items())
            return client.send("OK rooms " + ",".join(items))
    client.send("ERR 100 usage: LIST USERS|ROOMS")


def cmd_stats(client):
    with state_lock:
        line = (f"OK stats users={len(users)} rooms={len(rooms)} connections={active} "
                f"msgs_in={stats['msgs_in']} deliveries={stats['deliveries']} "
                f"uptime={int(time.time() - stats['start'])}")
    client.send(line)


def dispatch(client, line):
    """Parse one line and run the command. Returns False to close the connection."""
    parts = line.split(" ", 1)
    cmd = parts[0].upper()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "QUIT":
        client.send("OK bye")
        return False
    if not client.allow():
        client.send("ERR 111 rate limited")
        log.warning("RATE-LIMIT %s", client.name or client.addr)
        return True
    if cmd == "PING":
        client.send("PONG")
    elif cmd == "REGISTER":
        cmd_register(client, arg)
    elif client.name is None:
        client.send("ERR 101 not registered")
    elif cmd == "JOIN":
        cmd_join(client, arg)
    elif cmd == "LEAVE":
        cmd_leave(client, arg)
    elif cmd == "ROOMMSG":
        cmd_roommsg(client, arg)
    elif cmd == "PRIVMSG":
        cmd_privmsg(client, arg)
    elif cmd == "LIST":
        cmd_list(client, arg)
    elif cmd == "STATS":
        cmd_stats(client)
    else:
        client.send("ERR 100 unknown command")
        log.warning("unknown command %r from %s", cmd[:20], client.name or client.addr)
    return True


# ---- per-client thread ----
def handle_client(conn, addr):
    global active
    client = Client(conn, addr)
    conn.settimeout(IDLE_TIMEOUT)
    log.info("CONNECT %s:%s", addr[0], addr[1])
    buf = b""
    discarding = False   # True while skipping the rest of an over-long line
    try:
        running = True
        while running:
            data = conn.recv(1024)
            if not data:
                break
            buf += data
            if discarding:
                if b"\n" not in buf:
                    buf = b""
                    continue
                buf = buf.split(b"\n", 1)[1]      # drop the tail of the long line
                discarding = False
            # a single recv may hold 0, 1, or many complete lines
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if len(raw) > MAX_LINE:
                    client.send("ERR 107 line too long")
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    if not dispatch(client, line):
                        running = False
                        break
            if len(buf) > MAX_LINE:   # no newline yet and already too long
                client.send("ERR 107 line too long")
                buf = b""
                discarding = True
    except socket.timeout:
        client.send("ERR 109 idle timeout")
        log.warning("TIMEOUT %s (idle > %ss)", client.name or client.addr, IDLE_TIMEOUT)
    except OSError as ex:
        log.warning("connection error %s: %s", client.name or client.addr, ex)
    finally:
        cleanup(client)
        client.close()
        with state_lock:
            active -= 1


def cleanup(client):
    notify = []   # (members, line) pairs, queued after releasing the lock
    with state_lock:
        if client.name:
            users.pop(client.name.lower(), None)
        for room in list(client.rooms):
            members = rooms.get(room)
            if members is None:
                continue
            members.discard(client)
            if members:
                notify.append((list(members), f"INFO {client.name} left {room}"))
            else:
                del rooms[room]
        client.rooms.clear()
        online = len(users)
    for members, line in notify:
        broadcast(members, line)
    log.info("DISCONNECT %s (%s) (online=%d)", client.name or "-", client.addr[0], online)


def reject_full(conn, addr):
    log.warning("REJECT %s:%s (server full, max %d)", addr[0], addr[1], MAX_CLIENTS)
    try:
        conn.settimeout(1)
        conn.sendall(b"ERR 110 server full\n")
    except OSError:
        pass
    finally:
        conn.close()


def _on_sigterm(signum, frame):
    raise KeyboardInterrupt


def main():
    global active
    setup_logging()
    signal.signal(signal.SIGTERM, _on_sigterm)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(128)
        log.info("Chat server v1.0 listening on %s:%s (max_clients=%d idle_timeout=%ss "
                 "rate_limit=%s outq=%d)", HOST, PORT, MAX_CLIENTS, IDLE_TIMEOUT,
                 RATE_LIMIT or "off", OUTQ_MAX)
        try:
            while True:
                conn, addr = srv.accept()
                with state_lock:
                    full = active >= MAX_CLIENTS
                    if not full:
                        active += 1
                if full:
                    reject_full(conn, addr)
                    continue
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            log.info("Server shutting down")


if __name__ == "__main__":
    main()

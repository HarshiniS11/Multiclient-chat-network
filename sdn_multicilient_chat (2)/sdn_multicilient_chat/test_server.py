"""Automated tests for the chat server (standard library only).

Run:  python3 tests/test_server.py | tee tests/test_results.txt
Starts its own server instances on ports 5055-5059; nothing needs to be running.
"""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(ROOT, "chat_server.py")
PUSH = ("INFO", "ROOMMSG", "PRIVMSG")
MAIN_PORT = 5055

passed = 0
failed = 0
count_lock = threading.Lock()


class T:
    """A tiny test client."""
    def __init__(self, port=MAIN_PORT):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.buf = b""

    def send(self, line):
        self.sock.sendall((line + "\n").encode())

    def recv(self):
        """Next line of any kind, or None on timeout/close."""
        self.sock.settimeout(2)
        while b"\n" not in self.buf:
            try:
                d = self.sock.recv(4096)
            except (socket.timeout, OSError):
                return None
            if not d:
                return None
            self.buf += d
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode()

    def reply(self):
        """Next OK/ERR/PONG line, skipping pushed INFO/ROOMMSG/PRIVMSG lines."""
        while True:
            line = self.recv()
            if line is None or not line.startswith(PUSH):
                return line

    def silent(self):
        """True if nothing arrives for a short while."""
        if self.buf:
            return False
        self.sock.settimeout(0.4)
        try:
            return self.sock.recv(1024) == b""   # closed counts as silent
        except socket.timeout:
            return True

    def close(self):
        self.sock.close()


def check(name, cond, detail=""):
    global passed, failed
    with count_lock:
        if cond:
            passed += 1
            print(f"PASS  {name}")
        else:
            failed += 1
            print(f"FAIL  {name}  {detail}")


def start_server(port, **env):
    full = dict(os.environ, CHAT_PORT=str(port),
                CHAT_LOG=os.path.join(tempfile.gettempdir(), f"chat_test_{port}.log"))
    full.update({k: str(v) for k, v in env.items()})
    proc = subprocess.Popen([sys.executable, SERVER], env=full,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    sys.exit(f"server on port {port} did not start")


def test_basic():
    print("\n-- registration, rooms, messaging, cleanup --")
    a, b, c = T(), T(), T()

    a.send("REGISTER alice")
    check("register alice", a.reply() == "OK registered alice")
    b.send("REGISTER ALICE")
    check("duplicate name rejected (case-insensitive)", b.reply() == "ERR 104 username taken")
    b.send("REGISTER bob")
    check("register bob", b.reply() == "OK registered bob")
    c.send("REGISTER carol")
    check("register carol", c.reply() == "OK registered carol")
    c.send("REGISTER carol2")
    check("second REGISTER on same connection rejected", c.reply() == "ERR 102 already registered")

    x = T()
    x.send("REGISTER a!")
    check("invalid username rejected", x.reply() == "ERR 103 invalid name")
    x.send("JOIN lab1")
    check("command before register rejected", x.reply() == "ERR 101 not registered")
    x.send("PING")
    check("PING works before register", x.reply() == "PONG")
    x.close()

    a.send("JOIN lab1")
    check("alice joins lab1", a.reply() == "OK joined lab1")
    b.send("JOIN lab1")
    check("bob joins lab1", b.reply() == "OK joined lab1")
    check("alice notified of bob joining", a.recv() == "INFO bob joined lab1")
    b.send("JOIN lab1")
    check("double join rejected", b.reply() == "ERR 108 already in room")

    a.send("ROOMMSG lab1 hi all")
    check("room message accepted", a.reply() == "OK sent")
    check("room member receives it", b.recv() == "ROOMMSG lab1 alice hi all")
    check("non-member receives nothing", c.silent())
    c.send("ROOMMSG lab1 hey")
    check("non-member cannot send to room", c.reply() == "ERR 105 not in that room")

    a.send("PRIVMSG bob secret stuff")
    check("private message accepted", a.reply() == "OK sent")
    check("recipient gets private message", b.recv() == "PRIVMSG alice secret stuff")
    check("third user gets nothing", c.silent())
    a.send("PRIVMSG zed hello")
    check("unknown recipient rejected", a.reply() == "ERR 106 user not found")

    a.send("BOGUS")
    check("unknown command rejected", a.reply() == "ERR 100 unknown command")
    a.send("ROOMMSG lab1")
    check("malformed ROOMMSG rejected", a.reply().startswith("ERR 100"))

    a.send("LIST USERS")
    check("list users", a.reply() == "OK users alice,bob,carol")
    a.send("LIST ROOMS")
    check("list rooms", a.reply() == "OK rooms lab1(2)")
    a.send("STATS")
    st = a.reply() or ""
    check("STATS counters", st.startswith("OK stats ") and "msgs_in=2" in st
          and "deliveries=2" in st, st)

    c.send("JOIN lab1")
    c.reply()
    a.recv()                                   # INFO carol joined
    b.sock.close()                             # abrupt disconnect, no QUIT
    check("room notified of abrupt disconnect", a.recv() == "INFO bob left lab1")
    f = T()
    f.send("REGISTER bob")
    check("name freed after disconnect", f.reply() == "OK registered bob")

    a.send("LEAVE lab1")
    check("LEAVE works", a.reply() == "OK left lab1")
    a.send("LEAVE lab1")
    check("LEAVE when not a member rejected", a.reply() == "ERR 105 not in that room")

    a.send("QUIT")
    check("clean QUIT", a.reply() == "OK bye")
    check("connection closed after QUIT", a.recv() is None)
    for t in (c, f):
        t.close()


def test_framing():
    print("\n-- TCP framing --")
    e = T()
    e.sock.sendall(b"REGI")
    time.sleep(0.2)
    e.sock.sendall(b"STER dave\n")
    check("fragmented command reassembled", e.reply() == "OK registered dave")
    e.sock.sendall(b"LIST USERS\nLIST ROOMS\n")
    r1, r2 = e.reply(), e.reply()
    check("two commands in one packet", bool(r1 and r1.startswith("OK users")
          and r2 and r2.startswith("OK rooms")), f"{r1!r} {r2!r}")
    e.sock.sendall(b"JOIN " + b"x" * 2000 + b"\n")
    check("over-long line rejected", e.reply() == "ERR 107 line too long")
    e.sock.sendall(b"A" * 5000 + b"\nPING\n")
    r1, r2 = e.reply(), e.reply()
    check("tail of long line discarded, next command still works",
          r1 == "ERR 107 line too long" and r2 == "PONG", f"{r1!r} {r2!r}")
    e.sock.sendall(b"\xff\xfe\xfd garbage\n")
    check("invalid UTF-8 does not crash server", e.reply() == "ERR 100 unknown command")
    e.close()


def test_concurrency(n=30, msgs=5):
    print("\n-- concurrency --")
    ok_count = [0]

    def worker(i):
        try:
            t = T()
            good = 0
            t.send(f"REGISTER load{i:02d}")
            good += t.reply() == f"OK registered load{i:02d}"
            t.send("JOIN loadroom")
            good += t.reply() == "OK joined loadroom"
            for k in range(msgs):
                t.send(f"ROOMMSG loadroom message {k}")
                good += t.reply() == "OK sent"
            t.close()
            with count_lock:
                ok_count[0] += good
        except Exception as ex:
            print("worker error:", ex)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    start = time.time()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    expected = n * (2 + msgs)
    check(f"{n} concurrent clients, {expected} operations", ok_count[0] == expected,
          f"got {ok_count[0]}")
    print(f"      ({time.time() - start:.2f}s for {n} clients)")


def test_idle_timeout():
    print("\n-- idle timeout (CHAT_IDLE_TIMEOUT=1) --")
    srv = start_server(5059, CHAT_IDLE_TIMEOUT=1)
    try:
        t = T(5059)
        t.send("REGISTER sleepy")
        t.reply()
        time.sleep(1.6)
        check("idle client told about timeout", t.recv() == "ERR 109 idle timeout")
        check("idle client disconnected", t.recv() is None)
        t2 = T(5059)
        t2.send("REGISTER sleepy")
        check("idle client's name freed", t2.reply() == "OK registered sleepy")
        t2.close()
    finally:
        srv.kill()


def test_overload():
    print("\n-- server overload (CHAT_MAX_CLIENTS=3) --")
    srv = start_server(5056, CHAT_MAX_CLIENTS=3)
    time.sleep(0.5)          # let the start-up probe connection finish closing
    try:
        cs = [T(5056) for _ in range(3)]
        for c in cs:
            c.send("PING")
        check("3 clients accepted", all(c.reply() == "PONG" for c in cs))
        extra = T(5056)
        check("4th client rejected with ERR 110", extra.recv() == "ERR 110 server full")
        check("rejected client disconnected", extra.recv() is None)
        cs[0].send("QUIT")
        cs[0].reply()
        ok = False
        for _ in range(20):
            time.sleep(0.1)
            n = T(5056)
            n.send("PING")
            if n.reply() == "PONG":
                ok = True
                n.close()
                break
            n.close()
        check("slot freed after a client leaves", ok)
        cs[1].send("PING")
        check("existing clients unaffected by overload", cs[1].reply() == "PONG")
    finally:
        srv.kill()


def test_rate_limit():
    print("\n-- rate limiting (CHAT_RATE_LIMIT=5) --")
    srv = start_server(5057, CHAT_RATE_LIMIT=5)
    try:
        t = T(5057)
        t.sock.sendall(b"PING\n" * 20)
        replies = [t.recv() for _ in range(20)]
        pongs = replies.count("PONG")
        limited = replies.count("ERR 111 rate limited")
        check("burst is limited", limited >= 10 and pongs >= 1, f"pongs={pongs} limited={limited}")
        time.sleep(1.2)
        t.send("PING")
        check("allowed again after the window", t.reply() == "PONG")
        t.send("QUIT")
        check("QUIT is never rate limited", t.reply() == "OK bye")
    finally:
        srv.kill()


def test_slow_consumer():
    print("\n-- slow consumer (CHAT_OUTQ_MAX=20) --")
    srv = start_server(5058, CHAT_OUTQ_MAX=20)
    try:
        slow = socket.socket()
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        slow.connect(("127.0.0.1", 5058))
        slow.sendall(b"REGISTER slowguy\nJOIN flood\n")      # then never reads again
        f = T(5058)
        f.send("REGISTER flooder")
        f.reply()
        f.send("JOIN flood")
        f.reply()
        for _ in range(20):                                    # wait until slowguy is in the room
            f.send("LIST ROOMS")
            if f.reply() == "OK rooms flood(2)":
                break
            time.sleep(0.1)
        pad = "x" * 900
        stalled = dropped = False
        sent = 0
        for i in range(200000):
            f.send(f"ROOMMSG flood {pad}")
            if f.reply() != "OK sent":
                stalled = True
                break
            sent += 1
            if i % 500 == 499:
                f.send("LIST USERS")
                if "slowguy" not in (f.reply() or ""):
                    dropped = True
                    break
        check("flooding client never blocked", not stalled, f"after {sent} messages")
        check("non-reading client dropped by server", dropped, f"after {sent} messages")
        f.send("PING")
        check("server still responsive", f.reply() == "PONG")
        slow.close()
        f.close()
    finally:
        srv.kill()


if __name__ == "__main__":
    server = start_server(MAIN_PORT)
    try:
        test_basic()
        test_framing()
        test_concurrency()
    finally:
        server.kill()
    test_idle_timeout()
    test_overload()
    test_rate_limit()
    test_slow_consumer()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

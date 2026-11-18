
"""Client blocking policies for the SDN chat network."""

from threading import RLock

CHAT_SERVER_IP = "10.0.0.10"
CHAT_SERVER_PORT = 5000

_blocked_clients = set()
_lock = RLock()


def block_client(ip_address):
    with _lock:
        _blocked_clients.add(ip_address)


def unblock_client(ip_address):
    with _lock:
        _blocked_clients.discard(ip_address)


def is_blocked(ip_address):
    with _lock:
        return ip_address in _blocked_clients


def get_blocked_clients():
    with _lock:
        return set(_blocked_clients)

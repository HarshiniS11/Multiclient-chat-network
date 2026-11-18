"""
protocol.py
Helpers for Role 2's TCP chat client.

Role 1's server uses UTF-8 plain-text commands, each terminated by '\n'.
The server's MAX_LINE is 1024 bytes, excluding the newline.
"""

MAX_LINE_CONTENT_BYTES = 1024
MAX_LINE_BYTES = MAX_LINE_CONTENT_BYTES + 1  # include terminating newline


class ProtocolError(Exception):
    """Raised when a message does not follow the line-based protocol."""


def encode_line(command):
    """Convert one command string into newline-terminated UTF-8 bytes."""
    if not isinstance(command, str):
        raise TypeError("Command must be a string.")

    if "\n" in command or "\r" in command:
        raise ProtocolError("A command cannot contain a newline.")

    data = (command + "\n").encode("utf-8")

    # Match the server: up to 1024 content bytes, plus the newline.
    if len(data) > MAX_LINE_BYTES:
        raise ProtocolError(
            f"Message is too long. Maximum content is "
            f"{MAX_LINE_CONTENT_BYTES} UTF-8 bytes."
        )

    return data


def read_line(reader):
    """
    Read exactly one newline-terminated server message.
    `reader` should be created with sock.makefile('rb').
    """
    data = reader.readline(MAX_LINE_BYTES)

    if data == b"":
        return None  # The peer closed the connection.

    if len(data) > MAX_LINE_BYTES:
        raise ProtocolError("Server sent a line longer than 1024 bytes plus newline.")

    if not data.endswith(b"\n"):
        raise ProtocolError("Received an incomplete or overlong line from the server.")

    # Strip only the line terminator; preserve message spaces.
    return data[:-1].decode("utf-8", errors="replace").removesuffix("\r")

"""
client.py
Role 2: TCP chat client for the Multi-Client Chat Network.

The client uses Role 1's plain-text, newline-delimited TCP protocol.
Commands:
  /join ROOM
  /leave ROOM
  /room ROOM MESSAGE
  /msg USER MESSAGE
  /users
  /rooms
  /ping
  /help
  /quit
"""

import argparse
import re
import socket
import threading

from protocol import encode_line, read_line, ProtocolError

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def receive_messages(reader, finished_event):
    """Read and display all server messages in the background."""
    try:
        while True:
            line = read_line(reader)
            if line is None:
                print("\n[INFO] Server closed the connection.")
                break
            if line:
                print(f"\n{line}")
    except (OSError, ProtocolError) as error:
        print(f"\n[CONNECTION ERROR] {error}")
    finally:
        finished_event.set()


def send_command(sock, command, send_lock):
    """Encode and send one command safely."""
    data = encode_line(command)
    with send_lock:
        sock.sendall(data)


def show_help():
    print(
        """
Available commands:
  /join ROOM              Join a chat room
  /leave ROOM             Leave a chat room
  /room ROOM MESSAGE      Send a message to everyone else in a room
  /msg USER MESSAGE       Send a private message to one user
  /users                  Show online users
  /rooms                  Show available rooms and member counts
  /ping                   Check whether the server is responding
  /help                   Show this help message
  /quit                   Disconnect from the server

Example:
  /join cn_lab
  /room cn_lab Hello everyone!
  /msg alice Hi Alice!
"""
    )


def convert_input_to_command(user_input):
    """Convert slash commands into the exact commands expected by Role 1."""
    if not user_input:
        return None

    if user_input == "/help":
        show_help()
        return None
    if user_input == "/users":
        return "LIST USERS"
    if user_input == "/rooms":
        return "LIST ROOMS"
    if user_input == "/ping":
        return "PING"
    if user_input == "/quit":
        return "QUIT"

    if user_input.startswith("/join "):
        room = user_input[len("/join "):].strip()
        if room:
            return f"JOIN {room}"
        print("Usage: /join ROOM")
        return None

    if user_input.startswith("/leave "):
        room = user_input[len("/leave "):].strip()
        if room:
            return f"LEAVE {room}"
        print("Usage: /leave ROOM")
        return None

    if user_input.startswith("/room "):
        rest = user_input[len("/room "):]
        room, separator, message = rest.partition(" ")
        message = message.strip()
        if room and separator and message:
            return f"ROOMMSG {room} {message}"
        print("Usage: /room ROOM MESSAGE")
        return None

    if user_input.startswith("/msg "):
        rest = user_input[len("/msg "):]
        username, separator, message = rest.partition(" ")
        message = message.strip()
        if username and separator and message:
            return f"PRIVMSG {username} {message}"
        print("Usage: /msg USER MESSAGE")
        return None

    print("Unknown command. Type /help to see the available commands.")
    return None


def run_client(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reader = None
    receiver_thread = None
    receiver_finished = threading.Event()
    send_lock = threading.Lock()

    try:
        print(f"Connecting to {host}:{port} ...")
        sock.connect((host, port))
        reader = sock.makefile("rb")

        # Validate locally using the same rule as Role 1's server.
        while True:
            username = input("Enter a username (3-16 letters, numbers or _): ").strip()
            if USERNAME_RE.fullmatch(username):
                break
            print("Invalid username. Use 3-16 letters, numbers or underscores.")

        # Registration is the first command sent after connecting.
        send_command(sock, f"REGISTER {username}", send_lock)
        response = read_line(reader)

        if response is None:
            print("The server closed the connection during registration.")
            return

        print(response)
        if not response.startswith("OK registered "):
            print("Registration failed. Disconnecting.")
            return

        print("\nConnected! Type /help to see the commands.")

        # Only this background thread reads from the socket after registration.
        receiver_thread = threading.Thread(
            target=receive_messages,
            args=(reader, receiver_finished),
            daemon=True,
        )
        receiver_thread.start()

        while not receiver_finished.is_set():
            try:
                user_input = input("\nYou: ").strip()
            except EOFError:
                user_input = "/quit"
            except KeyboardInterrupt:
                print("\nLeaving chat...")
                user_input = "/quit"

            if not user_input:
                continue

            command = convert_input_to_command(user_input)
            if command is None:
                continue

            try:
                send_command(sock, command, send_lock)
            except (OSError, ProtocolError) as error:
                print(f"Could not send command: {error}")
                break

            if command == "QUIT":
                # Server replies "OK bye", then closes this connection.
                receiver_finished.wait(timeout=2)
                break

    except (OSError, ProtocolError) as error:
        print(f"\n[ERROR] {error}")
    finally:
        # Closing the socket unblocks the receiver if it is waiting for data.
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        if receiver_thread is not None:
            receiver_thread.join(timeout=1)

        if reader is not None:
            try:
                reader.close()
            except OSError:
                pass

        sock.close()
        print("Client closed.")


def main():
    parser = argparse.ArgumentParser(description="Role 2 TCP Chat Client")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server IP address (default: 127.0.0.1 for local testing)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Server TCP port (default: 5000)",
    )
    args = parser.parse_args()
    run_client(args.host, args.port)


if __name__ == "__main__":
    main()

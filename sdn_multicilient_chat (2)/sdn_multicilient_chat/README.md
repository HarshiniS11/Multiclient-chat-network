\# Multi-Client Chat Network using TCP Socket Programming and SDN



\## 1. Project Overview

This project implements a multi-client chat application using TCP sockets and an SDN-controlled network. The chat server supports client registration, chat rooms, room messaging, private messaging, and concurrent connections. The SDN component provides a Mininet topology and an OpenFlow controller.



\## 2. Project Structure

\- `chat\_server.py` — TCP chat server

\- `client.py` — interactive chat client

\- `protocol.py` — client/server message protocol

\- `bench\_chat.py` — performance benchmark

\- `test\_server.py` — server test suite

\- `sdn/topology.py` — Mininet topology

\- `sdn/chat\_controller.py` — SDN controller

\- `sdn/policies.py` — SDN policy functions

\- `tests/test\_controller.py` — controller policy tests

\- `role1/`, `role2/`, `role3/` — role-wise source files and references



\## 3. Requirements

\- Python 3

\- Ubuntu/Linux environment for Mininet

\- Mininet and Open vSwitch

\- An OpenFlow-compatible SDN controller

\- OS-Ken, if used by the controller



\## 4. Running the Chat Application

From the project root, start the server:



&#x20;   python chat\_server.py



Open separate terminals for clients:



&#x20;   python client.py --host 127.0.0.1 --port 5000



Choose different usernames. Example client commands:



&#x20;   /join lab

&#x20;   /room lab Hello everyone

&#x20;   /users

&#x20;   /rooms

&#x20;   /msg bob Hello

&#x20;   /quit



\## 5. Running Tests

Compile the Python files:



&#x20;   python -m py\_compile chat\_server.py client.py protocol.py bench\_chat.py test\_server.py



Run the server test suite:



&#x20;   python -m unittest -v test\_server



Run the controller policy tests in the environment where OS-Ken is installed:



&#x20;   python -m unittest discover -s tests -p "test\_controller.py" -v



Record the actual test results, including failures.



\## 6. SDN and Mininet

Run the controller and Mininet topology in the supported Linux environment. Verify switch-controller connectivity, host connectivity, and TCP chat traffic between Mininet hosts. Demonstrate the SDN policy changing network behaviour and record the observed results.



\## 7. Performance Evaluation

Use `bench\_chat.py` to measure connection setup, message latency, and message delivery throughput. Record the test configuration and measured results. Compare baseline and SDN-controlled runs only after actually running both experiments.



\## 8. Limitations

Document any unverified integration, test failures, environmental constraints, or limitations observed during testing.



\## 9. Team Contributions

\- Role 1: TCP server and backend

\- Role 2: client and communication protocol

\- Role 3: SDN controller, topology and policy logic



\## 10. Reproduction

Follow the setup and execution instructions above. Run the chat application tests and the SDN/Mininet demonstration in their respective environments, and retain the output as submission evidence.


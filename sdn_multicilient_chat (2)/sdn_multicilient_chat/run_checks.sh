#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
mkdir -p evidence
ts=$(date +%Y%m%d_%H%M%S)

echo "== syntax check =="
# Fixed paths matching your actual directory structure
python3 -m py_compile chat_server.py test_server.py bench_chat.py client.py protocol.py sdn/chat_controller.py sdn/policies.py && echo "syntax OK"

echo; echo "== automated tests =="
python3 test_server.py | tee "evidence/test_results_${ts}.txt"
tests_rc=${PIPESTATUS[0]}

echo; echo "== loopback benchmark =="
CHAT_PORT=5099 CHAT_LOG="evidence/server_bench_${ts}.log" python3 chat_server.py >/dev/null 2>&1 &
srv=$!
sleep 1
python3 bench_chat.py --port 5099 --label loopback --csv evidence/bench_results.csv \
| tee "evidence/bench_loopback_${ts}.txt"
kill "$srv" 2>/dev/null

echo; echo "Evidence saved in evidence/ (suffix ${ts})"
exit "$tests_rc"
#!/usr/bin/env bash
# One command to produce Role 1 test evidence: syntax check, test suite, loopback benchmark.
# Usage (from anywhere):  bash scripts/run_checks.sh
# Output goes to evidence/ with a timestamp. Commit that folder as proof.
set -u
cd "$(dirname "$0")/.."
mkdir -p evidence
ts=$(date +%Y%m%d_%H%M%S)

echo "== syntax check =="
python3 -m py_compile server/chat_server.py tests/test_server.py tools/bench_chat.py && echo "syntax OK"

echo; echo "== automated tests =="
python3 tests/test_server.py | tee "evidence/test_results_${ts}.txt"
tests_rc=${PIPESTATUS[0]}

echo; echo "== loopback benchmark (reference only, not the Mininet result) =="
CHAT_PORT=5099 CHAT_LOG="evidence/server_bench_${ts}.log" python3 server/chat_server.py >/dev/null 2>&1 &
srv=$!
sleep 1
python3 tools/bench_chat.py --port 5099 --label loopback --csv evidence/bench_results.csv \
    | tee "evidence/bench_loopback_${ts}.txt"
kill "$srv" 2>/dev/null

echo; echo "Evidence saved in evidence/ (suffix ${ts})"
exit "$tests_rc"

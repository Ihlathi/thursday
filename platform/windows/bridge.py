"""Windows platform bridge process -- the real counterpart to `mocks/platform.py`.

    python run.py windows-platform          (or: python platform/windows/bridge.py)
    python platform/windows/bridge.py --self-check    read-only local probe, no Core needed

Connects to Core at ws://127.0.0.1:8765/v1/platform with AGENT_PLATFORM_TOKEN,
receives one ToolCall at a time and answers with a matching ToolResult.

Two structural details worth keeping if this file is rewritten:

* Every UI Automation call runs on a single worker thread that owns the COM
  apartment, so the receive loop stays responsive and COM is never touched from
  two threads. That is what lets a `cancel` frame be processed while a call is
  still running.
* A new Session (and therefore a fresh revision/ID generation) is created per
  connection, so a bridge restart cannot hand Core IDs minted against an older
  view of the desktop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(HERE))

from agent.contracts import envelope, validate  # noqa: E402
from agent.transport import client_connect  # noqa: E402

from winbridge import uia  # noqa: E402
from winbridge.executor import WindowsBridge  # noqa: E402


async def run(url: str, token: str, ready=None) -> None:
    ws = await client_connect(url, "platform", token)
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="uia", initializer=uia.com_init)

    async def runner(fn):
        return await loop.run_in_executor(pool, fn)

    bridge = WindowsBridge(runner=runner)
    pending: dict[str, set] = {}
    if ready:
        ready.set()
    print("Windows bridge connected. Real UI Automation actions are enabled.", flush=True)

    async def execute(message):
        result = await bridge.execute(message["task_id"], message["payload"])
        await ws.send(json.dumps(envelope("tool_result", result, message["task_id"], message["request_id"])))

    try:
        async for raw in ws:
            msg = validate(json.loads(raw))
            if msg["type"] == "tool_call":
                task = asyncio.create_task(execute(msg))
                pending.setdefault(msg["task_id"], set()).add(task)

                def finished(completed, task_id=msg["task_id"]):
                    pending[task_id].discard(completed)
                    if not completed.cancelled():
                        completed.exception()

                task.add_done_callback(finished)
            elif msg["type"] == "cancel":
                # Flag first so a call that has not yet committed refuses, then
                # cancel the awaiting tasks. An operation already inside a COM
                # call still finishes: no rollback is claimed.
                await bridge.cancel(msg["task_id"])
                for task in pending.get(msg["task_id"], set()):
                    task.cancel()
            else:
                raise ValueError("Unexpected Core message")
    finally:
        tasks = [t for group in pending.values() for t in group]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.shutdown(wait=False, cancel_futures=True)
        await ws.close()


def self_check() -> int:
    """Read-only local probe: confirms UIA/WMI/pycaw work before involving Core."""
    print("Windows bridge self-check (read-only; nothing is clicked or changed)\n")
    bridge = WindowsBridge()
    uia.com_init()

    checks = [
        ("uia available", lambda: uia.available()),
        ("workstation locked", lambda: uia.is_locked()),
        ("active window", lambda: uia.active_window()),
        ("ui snapshot", lambda: f"{len(bridge._snapshot_delta().get('elements', []))} elements"),
        ("machine state", lambda: sorted(bridge.adapters.system.machine_state().keys())),
    ]
    failures = 0
    for label, probe in checks:
        try:
            print(f"[OK]   {label}: {probe()}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")

    print(
        "\nA failure here means a Windows dependency is missing or blocked; "
        "install platform/windows/requirements.txt and re-run on Windows 11."
        if failures else "\nAll probes succeeded."
    )
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Windows platform bridge")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/v1/platform")
    parser.add_argument("--self-check", action="store_true", help="Run read-only local probes and exit")
    args = parser.parse_args()

    if args.self_check:
        raise SystemExit(self_check())

    token = os.environ.get("AGENT_PLATFORM_TOKEN")
    if not token:
        raise SystemExit("AGENT_PLATFORM_TOKEN is not set; see .env.example")
    try:
        asyncio.run(run(args.url, token))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

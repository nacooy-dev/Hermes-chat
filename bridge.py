#!/opt/homebrew/bin/python3.11
"""
Hermes WebChat Bridge (Streaming Version)
- WebSocket server (:6789) for browser
- NATS subscriber for programmatic access
- Direct AIAgent API call with stream_callback for real-time token streaming
"""

import asyncio
import codecs
import json
import os
import signal
import sys
import time

# ── Config ──────────────────────────────────────────
WS_HOST = "127.0.0.1"
WS_PORT = 6789
NATS_HOST = "127.0.0.1"
NATS_PORT = 4222
REQUEST_SUBJECT = "hermes.request"
HERMES_VENV_PYTHON = "/Users/lvyun/.hermes/hermes-agent/venv/bin/python"
HERMES_AGENT_PATH = "/Users/lvyun/.hermes/hermes-agent"

# Default model/provider (can be overridden per request)
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "sensenova"

# ── Streaming Bridge (uses AIAgent API) ─────────────

def _build_agent_script(query: str, model: str, provider: str,
                         session_id: str | None) -> str:
    """Build the Python script that runs AIAgent with streaming + approval support."""
    return f"""
import sys, os, asyncio, json
sys.path.insert(0, {repr(HERMES_AGENT_PATH)})
os.environ["PYTHONIOENCODING"] = "utf-8"

import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)

from run_agent import AIAgent
from tools.terminal_tool import set_approval_callback

def stream_cb(delta):
    log_prefixes = (
        "🤖 ", "🔑 ", "🛠️ ", "⚠️ ", "📊 ",
        "💬 ", "🎉 ", "✅ ", "❌ ", "🔥 ",
        "📝 ", "🎯 ", "🔧 ", "🚀 ", "⏱️ ",
    )
    if not any(delta.startswith(p) for p in log_prefixes):
        sys.stdout.write(delta)
        sys.stdout.flush()

def approval_cb(command, description, *, allow_permanent=True):
    req = json.dumps({{"command": command, "description": description, "allow_permanent": allow_permanent}})
    sys.stdout.write("\\x1eAPPROVAL\\x1e" + req + "\\x1e")
    sys.stdout.flush()
    choice = sys.stdin.readline().strip()
    return choice

set_approval_callback(approval_cb)

agent_kwargs = dict(
    model={repr(model)},
    provider={repr(provider)},
    quiet_mode=True,
    skip_context_files=True,
    skip_memory=True,
)
_session_id = {repr(session_id)}
if _session_id:
    agent_kwargs["session_id"] = _session_id

try:
    agent = AIAgent(**agent_kwargs)
    result = agent.run_conversation(
        user_message={repr(query)},
        stream_callback=stream_cb,
    )
    sid = getattr(agent, "session_id", None) or ""
except Exception as e:
    sys.stdout.write("\\n[Error: " + repr(e) + "]\\n")
    sid = ""
sys.stdout.write("\\x1eEND\\x1esession_id=" + sid + "\\x1e")
sys.stdout.flush()
"""


# ── Approval tracking ─────────────────────────────
pending_approvals: dict = {}  # websocket → asyncio.Future[str]

async def stream_hermes(query: str, model: str = DEFAULT_MODEL,
                         provider: str = DEFAULT_PROVIDER,
                         session_id: str | None = None,
                         ws_send=None, websocket=None) -> str | None:
    """Run AIAgent as an async subprocess, streaming tokens in real-time via ws_send."""
    script = _build_agent_script(query, model, provider, session_id)

    proc = await asyncio.create_subprocess_exec(
        HERMES_VENV_PYTHON, "-u", "-c", script,
        stdout=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={**dict(os.environ),
             "PYTHONPATH": HERMES_AGENT_PATH,
             "PYTHONIOENCODING": "utf-8",
             "HERMES_CONFIG_HOME": os.environ.get("HERMES_CONFIG_HOME", os.path.expanduser("~/.hermes"))},
    )

    SUBPROCESS_TIMEOUT = 600
    end_sentinel = b"\x1eEND\x1e"
    approval_sentinel = b"\x1eAPPROVAL\x1e"
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buffer = b""
    sid = None
    sentinel_found = False

    try:
        while True:
            chunk = await asyncio.wait_for(
                proc.stdout.read(4096), timeout=SUBPROCESS_TIMEOUT
            )
            if not chunk:
                break
            buffer += chunk
            data_processed = False
            while True:
                # Check for end sentinel
                idx = buffer.find(end_sentinel)
                if idx == 0 and not data_processed:
                    sentinel_found = True
                    tail = buffer[len(end_sentinel):]
                    for part in tail.split(b"\x1e"):
                        if part.startswith(b"session_id="):
                            sid = part.decode().split("=", 1)[1].strip()
                    buffer = b""
                    break
                # Check for approval request
                ap_idx = buffer.find(approval_sentinel)
                if ap_idx != -1:
                    # Decode and send anything before the approval request
                    pre = buffer[:ap_idx]
                    if pre:
                        text = decoder.decode(pre, final=False)
                        if text and ws_send:
                            await ws_send(text)
                    # Extract approval JSON (between \x1eAPPROVAL\x1e and next \x1e)
                    rest = buffer[ap_idx + len(approval_sentinel):]
                    end = rest.find(b"\x1e")
                    if end == -1:
                        # Incomplete approval payload, wait for more data
                        # Put back the unprocessed prefix
                        buffer = buffer[ap_idx:]
                        break
                    raw = rest[:end].decode("utf-8")
                    try:
                        app_data = json.loads(raw)
                    except json.JSONDecodeError:
                        app_data = {"command": raw, "description": ""}
                    buffer = rest[end + 1:]
                    # Send approval request to browser and wait
                    if ws_send and websocket:
                        fut = asyncio.get_running_loop().create_future()
                        pending_approvals[websocket] = fut
                        try:
                            await ws_send({"type": "approval", **app_data})
                            choice = await asyncio.wait_for(fut, timeout=120)
                        except asyncio.TimeoutError:
                            choice = "deny"
                        finally:
                            pending_approvals.pop(websocket, None)
                        # Write choice to subprocess stdin
                        proc.stdin.write((choice + "\n").encode())
                        await proc.stdin.drain()
                        data_processed = True
                        continue  # re-scan buffer for more content
                    else:
                        # No browser to ask — deny
                        proc.stdin.write(b"deny\n")
                        await proc.stdin.drain()
                        continue
                # Check for end sentinel at any position
                idx = buffer.find(end_sentinel)
                if idx != -1:
                    pre = buffer[:idx]
                    if pre:
                        text = decoder.decode(pre, final=False)
                        if text and ws_send:
                            await ws_send(text)
                    sentinel_found = True
                    tail = buffer[idx + len(end_sentinel):]
                    for part in tail.split(b"\x1e"):
                        if part.startswith(b"session_id="):
                            sid = part.decode().split("=", 1)[1].strip()
                    buffer = b""
                    break
                # Normal content — decode and stream
                text = decoder.decode(buffer, final=False)
                buffer = b""
                if text and ws_send:
                    await ws_send(text)
                break

        if sentinel_found:
            try:
                await asyncio.wait_for(proc.stdout.read(), timeout=5)
            except asyncio.TimeoutError:
                pass
    except asyncio.TimeoutError:
        proc.kill()
        if ws_send:
            await ws_send("\n\n[Response timeout - subprocess killed]")
        return None
    finally:
        tail = decoder.decode(b"", final=True)
        if tail and ws_send:
            await ws_send(tail)
        if proc.returncode is None:
            proc.kill()
        await proc.wait()

    return sid


# ── WebSocket Server (for browser) ──────────────────

async def ws_handler(websocket):
    """Handle a browser WebSocket connection with streaming output."""
    print(f"  Browser connected", flush=True)
    clients[websocket] = None  # websocket → session_id

    async def ws_send(data):
        """Send a message to the browser. Accepts string (stream token) or dict."""
        if websocket not in clients:
            return
        try:
            if isinstance(data, str):
                payload = {"type": "stream", "token": data}
            elif isinstance(data, dict):
                payload = data
            else:
                return
            await websocket.send(json.dumps(payload))
        except Exception:
            pass

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"message": raw}

            # Handle approval response from browser
            if data.get("type") == "approval_response":
                fut = pending_approvals.get(websocket)
                if fut and not fut.done():
                    fut.set_result(data.get("choice", "deny"))
                continue

            query = data.get("message", "")
            if not query:
                await websocket.send(json.dumps(
                    {"type": "error", "content": "Empty message"}))
                continue

            model = data.get("model", DEFAULT_MODEL)
            provider = data.get("provider", DEFAULT_PROVIDER)
            sid = data.get("session_id") or clients.get(websocket)

            # Send "done" to browser to clear any previous thinking indicator
            await websocket.send(json.dumps({"type": "done"}))

            print(f"  → {query[:50]}...", flush=True)
            start = time.time()

            sid = await stream_hermes(query, model, provider, sid, ws_send, websocket)
            elapsed = time.time() - start

            # Send final sentinel
            await websocket.send(json.dumps({
                "type": "response",
                "success": True,
                "content": "",  # content streamed via 'stream' events
                "session_id": sid,
                "elapsed": round(elapsed, 2),
            }))
            clients[websocket] = sid
            print(f"  ← done ({round(elapsed, 1)}s)", flush=True)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"  WS error: {e}", flush=True)
    finally:
        clients.pop(websocket, None)
        print(f"  Browser disconnected", flush=True)


# Global client registry
clients = {}  # websocket → session_id


async def start_ws_server():
    """Start the WebSocket server for browser connections."""
    try:
        import websockets
    except ImportError:
        print("✗ websockets not installed. Run: pip install websockets")
        sys.exit(1)

    server = await websockets.serve(
        ws_handler, WS_HOST, WS_PORT,
        ping_interval=30, ping_timeout=10
    )
    print(f"✓ WebSocket server at ws://{WS_HOST}:{WS_PORT}", flush=True)
    return server


# ── NATS Listener (non-streaming, programmatic access) ─

async def nats_listener(nc):
    """Listen for NATS requests (non-streaming)."""
    async def handler(msg):
        try:
            data = json.loads(msg.data.decode())
        except json.JSONDecodeError:
            data = {"message": msg.data.decode()}

        query = data.get("message", "")
        model = data.get("model", DEFAULT_MODEL)
        provider = data.get("provider", DEFAULT_PROVIDER)
        sid = data.get("session_id")

        print(f"\n  [NATS] → {query[:50]}...", flush=True)
        # For NATS, collect full response (no streaming)
        result = await _nats_call_hermes(query, model, provider, sid)
        reply_to = msg.reply or "hermes.response"
        await nc.publish(reply_to, json.dumps(result).encode())
        print(f"  [NATS] ← done ({result['elapsed']}s)", flush=True)

    await nc.subscribe(REQUEST_SUBJECT, cb=handler)
    print(f"✓ NATS listening on '{REQUEST_SUBJECT}'", flush=True)


async def _nats_call_hermes(query, model, provider, sid):
    """NATS: run hermes and collect full output (pipe mode)."""
    cmd = ["hermes", "chat", "-q", query, "-Q",
           "-m", model, "--provider", provider]
    if sid:
        cmd.extend(["--resume", sid])

    start = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    elapsed = time.time() - start

    output = stdout.decode("utf-8", "replace").strip()
    err = stderr.decode("utf-8", "replace").strip()

    nsid = None
    for line in err.splitlines():
        if line.startswith("session_id:"):
            nsid = line.split(":", 1)[1].strip()
            break

    return {
        "type": "response",
        "success": proc.returncode == 0,
        "content": output or err,
        "session_id": nsid,
        "elapsed": round(elapsed, 2),
        "error": err if proc.returncode != 0 else None,
    }


async def start_nats():
    """Connect to NATS."""
    try:
        from nats.aio.client import Client as NATS
    except ImportError:
        print("✗ nats-py not installed. Run: pip install nats-py")
        return None

    nc = NATS()
    try:
        await nc.connect(f"nats://{NATS_HOST}:{NATS_PORT}")
        print(f"✓ Connected to NATS at {NATS_HOST}:{NATS_PORT}", flush=True)
        return nc
    except Exception as e:
        print(f"  NATS unavailable (optional): {e}", flush=True)
        return None


# ── Main ───────────────────────────────────────────

async def main():
    print("", flush=True)
    print("  Hermes WebChat Bridge (Streaming)", flush=True)
    print("  ─────────────────────────────────", flush=True)
    print(f"  Browser: ws://{WS_HOST}:{WS_PORT}", flush=True)
    print(f"  NATS:    {REQUEST_SUBJECT}", flush=True)
    print(f"  Agent:   {HERMES_VENV_PYTHON}", flush=True)
    print("", flush=True)

    ws_server = await start_ws_server()
    nc = await start_nats()
    if nc:
        await nats_listener(nc)

    print("\n  Ready. Press Ctrl+C to stop.\n", flush=True)

    stop = asyncio.Future()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: stop.set_result(None))
    loop.add_signal_handler(signal.SIGTERM, lambda: stop.set_result(None))

    try:
        await stop
    finally:
        ws_server.close()
        if nc:
            await nc.close()
        print("\n  Stopped.")


if __name__ == "__main__":
    asyncio.run(main())

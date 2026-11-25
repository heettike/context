"""The archive's read-only tools over the internet, for AI apps that only take remote connectors (ChatGPT, claude.ai).

This puts one person's private history behind a URL, so it is OFF until the owner starts it, nothing here starts
it by itself, and what it serves is narrower than the local server:

  - the HTTP server binds to 127.0.0.1 only; the world reaches it only through a tunnel the owner starts
  - its port is one of its own, picked at random once and kept in remote.json, as the api's is: there is no fixed
    number to look for. it is never started beside another program listening on that port, which the tunnel would
    otherwise hand the internet to
  - the URL carries a long random secret in its path (/mcp/<43 characters>); a request without it gets 404, never
    a hint. `Authorization: Bearer <secret>` on /mcp is accepted too. `remote --rotate` replaces the secret at once
  - only the tools on the allowlist exist; phone numbers and email addresses are masked in everything
  - calls are capped per minute and per day, bodies and replies are capped in size
  - every call is written to remote.log: when, which tool, how big; never what was asked or answered

  python3 -m ctx mcp --http [--port N]   the server alone, on this Mac only
  python3 -m ctx remote --start          server + tunnel; prints {"url", "tunnel", "pid"}
  python3 -m ctx remote --stop | --status | --url | --rotate

What the protocol and the two clients need, read from their docs, not from memory:
  transport   https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
              one endpoint; POST a JSON-RPC message; a request may be answered with plain application/json (no SSE
              needed); a notification gets 202; GET gets 405 when no stream is offered; check Origin; a bad
              MCP-Protocol-Version gets 400; sessions are optional
  claude.ai   https://claude.com/docs/connectors/building/authentication  and  https://support.claude.com/en/articles/11175166
              authless servers ("No sign in") are supported; a 401 would start OAuth, so we never send one; the URL
              must be https on port 443
  chatgpt     https://developers.openai.com/api/docs/guides/developer-mode
              streaming HTTP; "No authentication" is offered; search/fetch tools are not required; tools carrying
              readOnlyHint are treated as read-only
  cloudflared https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
              `cloudflared tunnel --url http://localhost:N` prints a trycloudflare.com URL; no SSE (we send none)
  tailscale   https://tailscale.com/kb/1311/tailscale-funnel
              `tailscale funnel --https=443 N`; with --bg it would come back after a reboot, so we never pass --bg
Both clients accept an authless URL, so the scheme is the secret in the path: no OAuth server to get wrong.
"""
import collections, hmac, json, os, re, secrets, signal, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import paths

CONF = os.path.join(paths.HOME, "remote.json")      # the secret and the port. 0600
RUN = os.path.join(paths.HOME, "remote.run.json")   # what is running now: pids, port, tunnel, host. no secret
LOG = os.path.join(paths.HOME, "remote.log")        # one line per call: sizes only
TUNNEL_LOG = os.path.join(paths.HOME, "remote.tunnel.log")
DEFAULT_TOOLS = ["about_me", "search", "person", "facts", "open_loops", "sources"]
PER_MINUTE, PER_DAY = 30, 1000
MAX_BODY = 64 * 1024            # bytes of one request
MAX_OUT = 16_000                # characters one tool may return to a remote caller
AT_ONCE = 4                     # tool calls running at the same moment
ORIGINS = ("https://claude.ai", "https://chatgpt.com", "https://chat.openai.com")     # a browser page elsewhere may not call this
INSTALL = "no tunnel program on this mac. install cloudflared, or set up tailscale funnel, then start again"
TAKEN = ("another program is already listening on port %d, so the remote endpoint was not started: the tunnel would hand the internet "
         "to whatever is there. see what it is: lsof -nP -iTCP:%d -sTCP:LISTEN")


def _write_private(path, data):
    tmp = path + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _conf():
    try:
        with open(CONF) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def secret(create=True):
    """The secret in force. Made on first use; kept in remote.json, readable by the owner only."""
    s = _conf().get("secret", "")
    if isinstance(s, str) and len(s) >= 43:
        return s
    return rotate() if create else ""


def rotate():
    """A new secret. The old URL stops working at the next request: the server re-reads the file when it changes."""
    s = secrets.token_urlsafe(32)       # 43 url-safe characters, 256 bits
    _write_private(CONF, dict(_conf(), secret=s, made=int(time.time())))        # the port stays as it was
    return s


class NoPort(Exception):
    """No free port could be found for the remote endpoint."""


def _free(port):
    """Can a server bind this port on 127.0.0.1 right now?"""
    import socket
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", int(port)))
        return True
    except (OSError, ValueError, OverflowError):
        return False


def stored_port():
    """The port this install's remote endpoint listens on: one of its own, picked at random once from 49152 to 65535 and
    kept in remote.json, as the api keeps its own (api.port). There is no well-known number to go looking at, and none is
    fallen back to: when no free one is found, nothing is started."""
    p = _conf().get("port")
    if isinstance(p, int) and not isinstance(p, bool) and 1024 < p < 65536:
        return p
    for _ in range(40):
        p = 49152 + secrets.randbelow(65535 - 49152)
        if _free(p):
            break
    else:
        raise NoPort("no free port between 49152 and 65535 could be taken on this mac after 40 tries, so the remote endpoint was not started. try again")
    _write_private(CONF, dict(_conf(), port=p))
    return p


def taken(port):
    """Is another program already listening on this port? lsof's list of listeners (api.listening), and a bind on
    127.0.0.1 for one it cannot see."""
    from . import api
    return bool(api.listening(port)) or not _free(port)


def allowed_tools():
    try:
        from . import settings
        return list(settings.load().get("remote_tools") or DEFAULT_TOOLS)
    except Exception:
        return list(DEFAULT_TOOLS)


def log(row):
    """Sizes and names only. Nothing a caller sent and nothing we answered is ever written here."""
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps(dict(row, at=int(time.time()))) + "\n")
    except OSError:
        pass


def _calls(since):
    n, last = 0, 0
    try:
        with open(LOG) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("tool") and r.get("at", 0) >= since:
                    n += 1
                last = max(last, r.get("at", 0)) if r.get("tool") else last
    except OSError:
        pass
    return n, last


def _midnight(now=None):
    return time.mktime(time.localtime(now or time.time())[:3] + (0, 0, 0, 0, 0, -1))


class Gate:
    """The secret, re-read when its file changes, and the caps on calls."""

    def __init__(self, per_minute=PER_MINUTE, per_day=PER_DAY):
        self.per_minute, self.per_day = per_minute, per_day
        self.lock = threading.Lock()
        self.recent = collections.deque()
        self.day, self.today = _midnight(), _calls(_midnight())[0]
        self.busy = threading.Semaphore(AT_ONCE)
        self.clients = {}               # session id -> client name given at initialize
        self._secret, self._mtime = "", None

    def secret(self):
        try:
            m = os.stat(CONF).st_mtime_ns
        except OSError:
            m = None
        if m != self._mtime or not self._secret:
            self._secret, self._mtime = secret(), None
            try:
                self._mtime = os.stat(CONF).st_mtime_ns
            except OSError:
                pass
        return self._secret

    def opens(self, path, authorization):
        """Is this request holding the secret? Compared in constant time; the path may carry it, or a Bearer header on /mcp."""
        want = self.secret().encode()
        got = path.split("?", 1)[0].encode("utf-8", "replace")
        in_path = hmac.compare_digest(got, b"/mcp/" + want)
        bearer = authorization.encode("utf-8", "replace") if isinstance(authorization, str) else b""
        in_header = got == b"/mcp" and hmac.compare_digest(bearer, b"Bearer " + want)
        return in_path or in_header

    def take(self):
        """Count one tool call. "" when it may run, else which cap it hit."""
        now = time.time()
        with self.lock:
            if now - self.day >= 86400:
                self.day, self.today = _midnight(now), 0
            awake = time.monotonic()            # the minute is a minute awake; the day is the calendar's
            while self.recent and awake - self.recent[0] > 60:
                self.recent.popleft()
            if len(self.recent) >= self.per_minute:
                return "minute"
            if self.today >= self.per_day:
                return "day"
            self.recent.append(awake)
            self.today += 1
            return ""


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version, protocol_version = "context", "", "HTTP/1.1"
    timeout = 30                        # a caller that stops sending does not hold a thread for long

    def log_message(self, *a):          # the default writes the request line, which holds the secret: write nothing
        pass

    def log_error(self, *a):
        pass

    def reply(self, code, body=None, headers=()):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)
        return len(raw)

    def error(self, code, rpc, message, mid=None, headers=()):
        return self.reply(code, {"jsonrpc": "2.0", "id": mid, "error": {"code": rpc, "message": message}}, headers)

    def known(self):
        gate = self.server.gate
        if not gate.opens(self.path, self.headers.get("Authorization")):
            self.reply(404)             # not 401: nothing here admits that an endpoint exists, and no client is sent into OAuth
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in ORIGINS and not re.fullmatch(r"https?://(127\.0\.0\.1|localhost)(:\d+)?", origin):
            self.reply(403)
            return False
        return True

    def refuse(self):
        if self.known():
            self.reply(405, headers=[("Allow", "POST")])

    do_GET = do_DELETE = do_PUT = do_PATCH = do_HEAD = do_OPTIONS = refuse

    def do_POST(self):
        from . import mcp
        gate = self.server.gate
        if not self.known():
            return
        try:
            size = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self.error(411, -32600, "content-length is required")
        if size > MAX_BODY or size < 0:
            self.close_connection = True
            return self.error(413, -32600, "request too large")
        version = self.headers.get("MCP-Protocol-Version")
        if version and version not in mcp.VERSIONS:
            return self.error(400, -32600, "unsupported protocol version")
        try:
            m = json.loads(self.rfile.read(size).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.error(400, -32700, "parse error")
        if not isinstance(m, dict):     # one message per request; batches left the protocol
            return self.error(400, -32600, "invalid request")
        session = str(self.headers.get("Mcp-Session-Id") or "")[:80]
        client = gate.clients.get(session, "unknown")
        method, headers = m.get("method"), []
        is_call = method == "tools/call" and "id" in m
        params = m.get("params") if isinstance(m.get("params"), dict) else {}
        tool = str(params.get("name"))[:40] if is_call else ""
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        sizes = {str(k)[:20]: len(str(v)) for k, v in list(args.items())[:8]}
        if is_call:
            over = gate.take()
            if over or not gate.busy.acquire(blocking=False):
                log({"tool": tool, "args": sizes, "bytes_out": 0, "client": client, "status": 429})
                return self.error(429, -32000, "too many calls this %s. try later." % (over or "moment"), m.get("id"), [("Retry-After", "60" if over != "day" else "3600")])
        try:
            out = mcp.handle(m, allow=allowed_tools(), strict=True, most=MAX_OUT)
        finally:
            if is_call:
                gate.busy.release()
        if method == "initialize" and isinstance(out, dict) and "result" in out:
            info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
            client = re.sub(r"[^\w .\-]", "", str(info.get("name") or "unknown"))[:40] or "unknown"
            session = secrets.token_urlsafe(18)
            if len(gate.clients) > 500:
                gate.clients.clear()
            gate.clients[session] = client
            headers.append(("Mcp-Session-Id", session))
        sent = self.reply(202) if out is None else self.reply(200, out, headers)
        if is_call or method == "initialize":
            row = {"args": sizes, "bytes_out": sent, "client": client, "status": 200}
            log(dict(row, tool=tool) if is_call else dict(row, method="initialize"))


def make_server(port=0, gate=None):
    """The HTTP server, bound to this Mac only. There is no way to ask it for another address."""
    srv = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    srv.daemon_threads = True
    srv.gate = gate or Gate()
    return srv


def serve(port=None):
    srv = make_server(stored_port() if port is None else port)
    srv.gate.secret()
    print(f"context: listening on 127.0.0.1:{srv.server_address[1]} (this mac only)", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


# ---- starting and stopping, with a tunnel the owner chose to open ------------------------------------------------

def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _is(pid, word):
    """Is that pid still the program we started? A pid is reused by the system, so it is checked before any kill."""
    try:
        r = subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True, timeout=5)
        return word in r.stdout
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False


def _run_state():
    try:
        with open(RUN) as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _find_url(text, kind):
    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com" if kind == "cloudflared" else r"https://[a-z0-9.-]+\.ts\.net", text or "")
    return m.group(0) if m else ""


def open_tunnel(port, which=None, popen=None, run=None, wait=40, sleep=time.sleep):
    """Start the first tunnel program found. Returns {"tunnel", "pid", "base"} or {"error"}. Never installs anything."""
    import shutil
    which, popen, run = which or shutil.which, popen or subprocess.Popen, run or subprocess.run
    cf, ts = which("cloudflared"), which("tailscale")
    if not cf and not ts:
        return {"error": INSTALL}
    kind = "cloudflared" if cf else "tailscale"
    cmd = [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"] if cf else [ts, "funnel", "--https=443", str(port)]      # no --bg: it must not outlive us
    out = open(TUNNEL_LOG, "w")
    try:
        p = popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    finally:
        out.close()
    base, waited = "", 0.0
    while waited < wait and not base:
        if p.poll() is not None:
            break
        sleep(0.5)
        waited += 0.5
        try:
            with open(TUNNEL_LOG, errors="replace") as f:
                base = _find_url(f.read(), kind)
        except OSError:
            pass
        if not base and kind == "tailscale" and waited >= 2:
            try:
                base = _find_url(run([ts, "funnel", "status"], capture_output=True, text=True, timeout=10).stdout, kind)
            except (OSError, subprocess.SubprocessError):
                pass
    if not base:
        if p.poll() is None:
            p.terminate()
        return {"error": f"{kind} started but gave no public address in {int(wait)} seconds. see remote.tunnel.log in the archive folder"}
    return {"tunnel": kind, "pid": p.pid, "base": base}


def start(port=None, local=False, which=None, popen=None, run=None, wait=40, sleep=time.sleep, busy=None):
    """Server, then tunnel. One dict: {"url", "tunnel", "pid"} or {"error"}. The url holds the secret: it is returned
    to the caller to show the owner and written nowhere else. port: this install's own (stored_port) unless given. Nothing
    is started when another program already listens on it (busy, for tests: taken): the secret would be sent to that
    program, and the tunnel would put it on the internet."""
    popen = popen or subprocess.Popen
    st = _run_state()
    if st.get("pid") and _alive(st["pid"]):
        return {"error": "already running. stop it first: python3 -m ctx remote --stop"}
    try:
        port = stored_port() if port is None else int(port)
    except NoPort as e:
        return {"error": str(e)}
    if (busy or taken)(port):
        return {"error": TAKEN % (port, port)}
    s = secret()
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from . import guard
    srv = popen(guard.python(["mcp", "--http", "--port", str(port)]), cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True, env=dict(os.environ, PYTHONPATH=repo))
    state = {"pid": srv.pid, "port": port, "tunnel": "", "tunnel_pid": 0, "host": "", "started": int(time.time())}
    if local:
        _write_private(RUN, state)
        return {"url": f"http://127.0.0.1:{port}/mcp/{s}", "tunnel": "", "pid": srv.pid}
    t = open_tunnel(port, which, popen, run, wait, sleep)
    if "error" in t:
        try:
            srv.terminate()
        except OSError:
            pass
        return {"error": t["error"]}
    state.update(tunnel=t["tunnel"], tunnel_pid=t["pid"], host=t["base"].split("//", 1)[1])
    _write_private(RUN, state)
    return {"url": f'{t["base"]}/mcp/{s}', "tunnel": t["tunnel"], "pid": srv.pid}


def stop(kill=os.kill):
    st, done = _run_state(), []
    for key, word in (("tunnel_pid", st.get("tunnel") or "tunnel"), ("pid", "ctx")):
        pid = st.get(key)
        if pid and _alive(pid) and _is(pid, word):
            try:
                kill(int(pid), signal.SIGTERM)
                done.append(key)
            except OSError:
                pass
    try:
        os.remove(RUN)
    except OSError:
        pass
    return {"stopped": bool(done), "was_running": bool(st)}


def status():
    """Running or not, which tunnel, the host only (never the path), calls today and the last call."""
    st = _run_state()
    running = bool(st.get("pid")) and _alive(st["pid"])
    tunnel_up = bool(st.get("tunnel_pid")) and _alive(st["tunnel_pid"])
    today, last = _calls(_midnight())
    try:
        from . import settings
        auto = settings.load().get("remote_autostart") == "on"
    except Exception:
        auto = False
    return {"running": running, "tunnel": st.get("tunnel", "") if running and tunnel_up else "", "host": st.get("host", "") if running and tunnel_up else "",
            "port": st.get("port") if running else None, "local_only": running and not tunnel_up, "calls_today": today, "last_call": last,
            "tools": allowed_tools(), "limits": {"per_minute": PER_MINUTE, "per_day": PER_DAY, "reply_chars": MAX_OUT}, "autostart": auto,
            "has_secret": bool(secret(create=False))}


def url():
    """The full address to paste into ChatGPT or claude.ai, for the owner's eyes. {"url"} or {"error"}."""
    st = status()
    if not st["running"]:
        return {"error": "remote is off. start it: python3 -m ctx remote --start"}
    base = "https://" + st["host"] if st["host"] else f'http://127.0.0.1:{st["port"]}'
    return {"url": f"{base}/mcp/{secret()}", "tunnel": st["tunnel"]}


def main(args):
    if "--start" in args:
        port = next((int(a) for a in args if a.isdigit()), None)
        out = start(port, local="--local" in args)
    elif "--stop" in args:
        out = stop()
    elif "--rotate" in args:
        rotate()
        out = {"rotated": True, "note": "the old url no longer works. get the new one: python3 -m ctx remote --url"}
    elif "--url" in args:
        out = url()
    else:
        out = status()
    print(json.dumps(out))
    return 1 if "error" in out else 0

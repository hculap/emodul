"""Browser-based login flow.

Spins up a tiny local HTTP server on 127.0.0.1, opens the user's default
browser to a sign-in form, accepts the POSTed credentials, calls eModul
auth, and returns the resulting token to the CLI.

Why: when an AI agent runs `emodul auth login --browser`, the user types
the password into the BROWSER (separate process). The agent's terminal
never sees the password — only a success signal. This is the same flow
as `gh auth login`, `gcloud auth login`, etc.

Security:
- Bind 127.0.0.1 only (never 0.0.0.0)
- Random CSRF `state` token in the URL; rejected if absent or wrong
- Single-use server: shuts down after first successful auth
- Configurable timeout (default 5 min)
- HTML form makes the trust boundary explicit to the user
"""
from __future__ import annotations

import http.server
import json
import secrets
import threading
import webbrowser
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from emodul.api import ApiClient, EmodulApiError
from emodul.format import err_console


class LoginFlowError(Exception):
    """Raised when the browser login flow cannot complete.

    Causes: local port bind failure, user-cancel (Ctrl-C), timeout, or
    the server returning a malformed auth response. Subclasses Exception
    (not BaseException) so it propagates cleanly through `@safely` in
    MCP tools — earlier we raised SystemExit which killed the server.
    """

# Single-file HTML/CSS/JS. Apple-system aesthetic, system dark mode aware.
_HTML_FORM = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>emodul · sign in</title>
  <style>
    :root {
      --bg: #f5f5f7;
      --card: #ffffff;
      --text: #1d1d1f;
      --text-secondary: #6e6e73;
      --border: #d2d2d7;
      --input-bg: #ffffff;
      --accent: #0071e3;
      --accent-hover: #0077ed;
      --success: #34c759;
      --error: #ff3b30;
      --error-bg: rgba(255, 59, 48, 0.08);
      --safety-bg: rgba(0, 0, 0, 0.03);
      --shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #000000;
        --card: #1c1c1e;
        --text: #f5f5f7;
        --text-secondary: #98989d;
        --border: #38383a;
        --input-bg: #2c2c2e;
        --error-bg: rgba(255, 59, 48, 0.15);
        --safety-bg: rgba(255, 255, 255, 0.05);
        --shadow: 0 4px 24px rgba(0, 0, 0, 0.6);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      -webkit-font-smoothing: antialiased;
    }
    .card {
      background: var(--card);
      border-radius: 18px;
      padding: 40px 32px 28px;
      width: 100%;
      max-width: 380px;
      box-shadow: var(--shadow);
    }
    .logo {
      width: 56px;
      height: 56px;
      margin: 0 auto 20px;
      background: linear-gradient(135deg, #ff6b35, #f7931e);
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 28px;
      box-shadow: 0 4px 12px rgba(255, 107, 53, 0.3);
    }
    h1 {
      margin: 0 0 6px;
      font-size: 22px;
      font-weight: 600;
      text-align: center;
      letter-spacing: -0.02em;
    }
    p.sub {
      color: var(--text-secondary);
      font-size: 14px;
      text-align: center;
      margin: 0 0 28px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 500;
      margin-bottom: 6px;
      color: var(--text);
    }
    input {
      width: 100%;
      padding: 11px 13px;
      border: 1px solid var(--border);
      border-radius: 10px;
      font-size: 15px;
      font-family: inherit;
      margin-bottom: 16px;
      background: var(--input-bg);
      color: var(--text);
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    input:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 4px rgba(0, 113, 227, 0.15);
    }
    button {
      width: 100%;
      padding: 12px;
      background: var(--accent);
      color: white;
      border: none;
      border-radius: 10px;
      font-size: 15px;
      font-weight: 500;
      font-family: inherit;
      cursor: pointer;
      transition: background 0.15s, opacity 0.15s;
    }
    button:hover:not(:disabled) { background: var(--accent-hover); }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .error {
      color: var(--error);
      font-size: 13px;
      margin: 0 0 14px;
      padding: 9px 12px;
      background: var(--error-bg);
      border-radius: 8px;
    }
    .safety {
      font-size: 11px;
      color: var(--text-secondary);
      text-align: center;
      margin-top: 18px;
      padding: 10px;
      background: var(--safety-bg);
      border-radius: 8px;
      line-height: 1.5;
    }
    .safety code {
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 11px;
    }
    .footer {
      text-align: center;
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 18px;
    }
    .footer a { color: var(--accent); text-decoration: none; }
    .footer a:hover { text-decoration: underline; }
    /* Success state */
    .success { text-align: center; padding: 12px 0; }
    .success-icon {
      width: 64px;
      height: 64px;
      margin: 0 auto 18px;
      background: var(--success);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 36px;
      animation: pop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
      box-shadow: 0 4px 16px rgba(52, 199, 89, 0.3);
    }
    @keyframes pop {
      0%   { transform: scale(0); opacity: 0; }
      60%  { transform: scale(1.1); }
      100% { transform: scale(1); opacity: 1; }
    }
    .meta {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 14px;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
    }
  </style>
</head>
<body>
  <div class="card" id="card">
    <div class="logo">🔥</div>
    <h1>Sign in to emodul</h1>
    <p class="sub">Connect the CLI to your <strong>eModul.pl</strong> account</p>

    <form id="loginForm" autocomplete="on">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" required autofocus
             autocomplete="username" inputmode="email">

      <label for="password">Password</label>
      <input type="password" id="password" name="password" required
             autocomplete="current-password">

      <button type="submit" id="submitBtn">Sign in</button>
    </form>

    <div class="safety">
      🔒 Your password is sent only to <code>emodul.pl</code>.
      The AI agent that ran <code>emodul auth login</code> never sees it.
    </div>

    <div class="footer">
      <a href="https://github.com/hculap/emodul" target="_blank" rel="noopener">
        emodul on GitHub
      </a>
    </div>
  </div>

  <script>
    const form = document.getElementById('loginForm');
    const btn = document.getElementById('submitBtn');
    const card = document.getElementById('card');
    const state = new URLSearchParams(window.location.search).get('state');

    function showError(msg) {
      const existing = form.querySelector('.error');
      if (existing) existing.remove();
      const err = document.createElement('div');
      err.className = 'error';
      err.textContent = msg;
      form.insertBefore(err, form.firstChild);
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      btn.disabled = true;
      btn.textContent = 'Signing in…';
      const formData = new FormData(form);
      try {
        const resp = await fetch(
          '/submit?state=' + encodeURIComponent(state),
          { method: 'POST', body: formData }
        );
        const data = await resp.json();
        if (data.ok) {
          card.innerHTML = `
            <div class="success">
              <div class="success-icon">✓</div>
              <h1>Signed in</h1>
              <p class="sub">Connected as <strong>${data.email}</strong></p>
              <p class="meta">user_id: ${data.user_id}</p>
              <p class="sub" style="margin-top: 24px; font-size: 13px;">
                You can close this tab. The CLI is ready.
              </p>
            </div>
          `;
          setTimeout(() => { try { window.close(); } catch (_) {} }, 1500);
        } else {
          btn.disabled = false;
          btn.textContent = 'Sign in';
          showError(data.error || 'Login failed');
        }
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Sign in';
        showError('Network error: ' + err.message);
      }
    });
  </script>
</body>
</html>
"""


def _make_handler(state_token: str, base_url: str, language_id: int,
                  done_event: threading.Event, result: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            params = self._parse_query(parsed.query)
            if params.get('state') != state_token:
                self.send_response(403)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Invalid or missing state token. '
                                 b'This server only accepts the URL printed by the CLI.')
                return
            html = _HTML_FORM.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != '/submit':
                self.send_response(404)
                self.end_headers()
                return
            params = self._parse_query(parsed.query)
            if params.get('state') != state_token:
                self._json(403, {'ok': False, 'error': 'CSRF state mismatch'})
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            form = parse_qs(body)
            email = (form.get('email') or [''])[0].strip()
            password = (form.get('password') or [''])[0]
            if not email or not password:
                self._json(400, {'ok': False, 'error': 'Email and password are required.'})
                return
            try:
                with ApiClient(base_url=base_url) as api:
                    resp = api.authenticate(email, password, language_id)
            except EmodulApiError as exc:
                msg = 'Invalid email or password' if exc.status == 401 \
                      else f'eModul API error {exc.status}'
                status = exc.status if 400 <= exc.status < 500 else 500
                self._json(status, {'ok': False, 'error': msg})
                return
            except Exception as exc:  # network / DNS / unexpected
                self._json(500, {'ok': False, 'error': f'Network error: {exc}'})
                return
            token = resp.get('token')
            user_id = resp.get('user_id')
            if not token or not user_id:
                self._json(500, {'ok': False,
                                 'error': f'Unexpected auth response: {resp}'})
                return
            # Store result + signal main thread (after we send the response)
            result['token'] = token
            result['user_id'] = int(user_id)
            result['email'] = email
            result['password'] = password
            self._json(200, {'ok': True, 'email': email, 'user_id': int(user_id)})
            done_event.set()

        @staticmethod
        def _parse_query(query: str) -> dict[str, str]:
            return {k: v[0] for k, v in parse_qs(query).items()}

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            # Suppress default request log spam to stderr
            return

    return Handler


class LoginSession:
    """Handle to a running login HTTP server. Created by `start_login_server`,
    consumed by `wait_for_login` (or discarded via `cancel_login`).
    """

    def __init__(
        self,
        server: http.server.ThreadingHTTPServer,
        state_token: str,
        done: threading.Event,
        result: dict[str, Any],
        url: str,
    ) -> None:
        self.server = server
        self.state_token = state_token
        self.done = done
        self.result = result
        self.url = url


def start_login_server(
    base_url: str,
    *,
    language_id: int = 18,
    open_browser: bool = True,
    port: int | None = None,
    on_url: Callable[[str], None] | None = None,
) -> LoginSession:
    """Bind the local login server, open the browser, return a session handle.

    Does NOT wait for the user to submit. Callers must subsequently call
    `wait_for_login(session, timeout=...)` to block, or `cancel_login(session)`
    to abandon. Use this when the consumer (e.g. an MCP tool) needs to return
    the URL without holding the call open.

    Raises `LoginFlowError` only on server-bind failure (rare).
    """
    state_token = secrets.token_urlsafe(24)
    bind_port = port if port else 0
    done = threading.Event()
    result: dict[str, Any] = {}

    handler_class = _make_handler(state_token, base_url, language_id, done, result)
    try:
        server = http.server.ThreadingHTTPServer(('127.0.0.1', bind_port), handler_class)
    except OSError as exc:
        raise LoginFlowError(f'Cannot bind 127.0.0.1:{bind_port}: {exc}') from exc

    actual_port = server.server_address[1]
    url = f'http://127.0.0.1:{actual_port}/?state={state_token}'

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    err_console.print()
    err_console.print('[bold]🔥 emodul login — open in your browser:[/bold]')
    err_console.print(f'   [cyan]{url}[/cyan]')

    if on_url is not None:
        try:
            on_url(url)
        except Exception:
            # Callback failures must not break the auth flow.
            pass

    if open_browser:
        try:
            if webbrowser.open(url):
                err_console.print('[dim](opened in default browser)[/dim]')
        except Exception:
            pass
    err_console.print()

    return LoginSession(server, state_token, done, result, url)


def wait_for_login(session: LoginSession, *, timeout: int) -> dict[str, Any]:
    """Block until the user submits the form or `timeout` elapses.

    Always shuts the server down on exit (success, timeout, KeyboardInterrupt).
    Raises `LoginFlowError` on timeout, cancel, or missing-token.
    """
    try:
        if not session.done.wait(timeout=timeout):
            session.server.shutdown()
            raise LoginFlowError(
                f'Login timed out after {timeout}s. Re-run with --timeout N to extend.'
            )
    except KeyboardInterrupt:
        session.server.shutdown()
        raise LoginFlowError('Login cancelled.') from None

    session.server.shutdown()
    if not session.result.get('token'):
        raise LoginFlowError('Login flow exited without a token (internal error).')
    return session.result


def cancel_login(session: LoginSession) -> None:
    """Stop the server early (e.g. before its timeout). Idempotent."""
    try:
        session.server.shutdown()
    except Exception:
        pass


def web_login_flow(
    base_url: str,
    *,
    language_id: int = 18,
    open_browser: bool = True,
    port: int | None = None,
    timeout: int = 300,
    on_url: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Blocking wrapper around `start_login_server` + `wait_for_login`.

    Used by the terminal CLI (`emodul auth login --browser`). For MCP /
    chat-agent contexts where blocking the tool call is harmful, call
    `start_login_server` directly and run `wait_for_login` in a background
    thread.

    Returns a dict with keys: `token`, `user_id`, `email`, `password`.
    Raises `LoginFlowError` on timeout, cancel, server-bind failure, or
    missing-token. CLI callers convert this to `SystemExit` themselves;
    MCP tools let `@safely` translate it into an error envelope.
    """
    session = start_login_server(
        base_url,
        language_id=language_id,
        open_browser=open_browser,
        port=port,
        on_url=on_url,
    )
    err_console.print(
        f'[dim]Waiting up to {timeout}s. Ctrl-C to cancel.[/dim]'
    )
    return wait_for_login(session, timeout=timeout)

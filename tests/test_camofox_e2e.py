import json
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
FETCHER_SCRIPTS_DIR = ROOT / "third_party" / "x_tweet_fetcher" / "scripts"

sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(FETCHER_SCRIPTS_DIR))

import collector  # noqa: E402


TIMELINE_SNAPSHOT = """- link [e1]:
- /url: /zerohedge/status/111#m
- link "zerohedge":
- link "@zerohedge":
- link "1m":
- text: Oil is higher
- text: 1  2  3
- link [e2]:
- /url: /zerohedge/status/222#m
- link "zerohedge":
- link "@zerohedge":
- link "2m":
- text: Stocks are lower
- text: 4  5  6
"""


class FakeCamofoxState:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with getattr(self, "lock", threading.Lock()):
            self.next_tab_id = 1
            self.sessions = {}
            self.deleted_sessions = []
            self.delete_tab_requests = []

    def create_tab(self, user_id: str, session_key: str) -> str:
        with self.lock:
            tab_id = f"tab-{self.next_tab_id}"
            self.next_tab_id += 1
            session = self.sessions.setdefault(user_id, {})
            session[tab_id] = {
                "session_key": session_key,
                "url": "about:blank",
            }
            return tab_id

    def navigate(self, user_id: str, tab_id: str, url: str) -> None:
        with self.lock:
            self.sessions[user_id][tab_id]["url"] = url

    def get_tab(self, user_id: str, tab_id: str):
        with self.lock:
            return self.sessions.get(user_id, {}).get(tab_id)

    def list_tabs(self, user_id: str):
        with self.lock:
            return list(self.sessions.get(user_id, {}).items())

    def delete_session(self, user_id: str) -> None:
        with self.lock:
            self.deleted_sessions.append(user_id)
            self.sessions.pop(user_id, None)

    def note_delete_tab(self, user_id: str, tab_id: str) -> None:
        with self.lock:
            self.delete_tab_requests.append((user_id, tab_id))

    def active_tabs(self) -> int:
        with self.lock:
            return sum(len(session) for session in self.sessions.values())


class FakeCamofoxHandler(BaseHTTPRequestHandler):
    state = FakeCamofoxState()

    def log_message(self, format, *args):
        return

    def _send_json(self, payload, status=200):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            return self._send_json(
                {
                    "ok": True,
                    "engine": "camoufox",
                    "browserConnected": True,
                    "browserRunning": True,
                    "activeTabs": self.state.active_tabs(),
                    "consecutiveFailures": 0,
                }
            )

        if parsed.path == "/tabs":
            user_id = parse_qs(parsed.query).get("userId", [""])[0]
            tabs = []
            for tab_id, tab in self.state.list_tabs(user_id):
                tabs.append(
                    {
                        "targetId": tab_id,
                        "tabId": tab_id,
                        "url": tab["url"],
                        "title": "Fake Nitter",
                        "listItemId": tab["session_key"],
                    }
                )
            return self._send_json({"running": True, "tabs": tabs})

        if parsed.path.startswith("/tabs/") and parsed.path.endswith("/snapshot"):
            user_id = parse_qs(parsed.query).get("userId", [""])[0]
            parts = parsed.path.strip("/").split("/")
            tab_id = parts[1]
            tab = self.state.get_tab(user_id, tab_id)
            if not tab:
                return self._send_json({"error": "Tab not found"}, status=404)
            return self._send_json({"snapshot": TIMELINE_SNAPSHOT, "url": tab["url"]})

        return self._send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_json()

        if parsed.path == "/tabs":
            user_id = body["userId"]
            session_key = body["sessionKey"]
            tab_id = self.state.create_tab(user_id, session_key)
            return self._send_json({"tabId": tab_id, "url": "about:blank"})

        if parsed.path.startswith("/tabs/") and parsed.path.endswith("/navigate"):
            parts = parsed.path.strip("/").split("/")
            tab_id = parts[1]
            user_id = body["userId"]
            self.state.navigate(user_id, tab_id, body["url"])
            return self._send_json({"ok": True, "tabId": tab_id, "url": body["url"]})

        return self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        parsed = urlparse(self.path)

        if parsed.path.startswith("/sessions/"):
            user_id = parsed.path.rsplit("/", 1)[-1]
            self.state.delete_session(user_id)
            return self._send_json({"ok": True})

        if parsed.path.startswith("/tabs/"):
            body = self._read_json()
            user_id = body.get("userId", "")
            tab_id = parsed.path.rsplit("/", 1)[-1]
            self.state.note_delete_tab(user_id, tab_id)
            # Intentionally do not remove the tab here.
            # The regression we care about is that the client now also
            # deletes the whole session, which is the reliable cleanup path.
            return self._send_json({"ok": True})

        return self._send_json({"error": "Not found"}, status=404)


class CamofoxRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeCamofoxHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        FakeCamofoxHandler.state.reset()

    def test_collector_following_fetch_cleans_up_camofox_session(self):
        fetcher_script = str(FETCHER_SCRIPTS_DIR / "fetch_tweet.py")
        candidates, failed_handles = collector._collect_following_via_fetcher(
            fetcher_script=fetcher_script,
            handles=["zerohedge"],
            per_source_limit=2,
            camofox_port=self.port,
            nitter_instances=["nitter.net"],
        )

        self.assertEqual(failed_handles, [])
        self.assertEqual([c.tweet_id for c in candidates], ["111", "222"])
        self.assertEqual(
            [c.url for c in candidates],
            [
                "https://x.com/zerohedge/status/111",
                "https://x.com/zerohedge/status/222",
            ],
        )
        self.assertEqual(FakeCamofoxHandler.state.active_tabs(), 0)
        self.assertEqual(FakeCamofoxHandler.state.sessions, {})
        self.assertGreaterEqual(len(FakeCamofoxHandler.state.deleted_sessions), 1)
        self.assertGreaterEqual(len(FakeCamofoxHandler.state.delete_tab_requests), 1)


if __name__ == "__main__":
    unittest.main()

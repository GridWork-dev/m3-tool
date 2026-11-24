from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from refs_helpers import make_image_bytes


@dataclass(frozen=True)
class SeenRequest:
    path: str
    user_agent: str


class Site:
    def __init__(self) -> None:
        self.requests: list[SeenRequest] = []
        self.routes: dict[str, tuple[int, bytes, str, dict[str, str]]] = {}
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                site.requests.append(SeenRequest(self.path, self.headers.get("User-Agent", "")))
                status, body, content_type, headers = site.routes.get(
                    self.path, (404, b"", "text/plain", {})
                )
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.add(
            "/robots.txt", body="User-agent: *\nDisallow: /private/\n", content_type="text/plain"
        )
        self.add("/ok.html", body='<img src="/big.jpg"><img src="/small.jpg">')
        self.add("/big.jpg", body=make_image_bytes(1), content_type="image/jpeg")
        self.add("/small.jpg", body=make_image_bytes(2, size=(300, 200)), content_type="image/jpeg")
        self.add("/private/page.html", body='<img src="/big.jpg">')
        self.add("/blocked.html", status=403)
        self.add("/checkpoint.html", status=429, body="<title>Vercel Security Checkpoint</title>")
        self.add("/challenge.html", body="<title>Just a moment...</title>")
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server.server_port}{path}"

    def add(
        self,
        path: str,
        *,
        status: int = 200,
        body: bytes | str = b"",
        content_type: str = "text/html",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.routes[path] = (
            status,
            body.encode() if isinstance(body, str) else body,
            content_type,
            headers or {},
        )

    def hits(self, path: str) -> int:
        return sum(r.path == path for r in self.requests)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def site() -> Iterator[Site]:
    instance = Site()
    try:
        yield instance
    finally:
        instance.close()

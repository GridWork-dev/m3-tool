from typing import Any

import httpx
from refs_helpers import FakeClock, make_image_bytes


class FakeWikimedia:
    def __init__(
        self, pages: list[dict[str, Any]], *, page_size: int = 2, clock: FakeClock | None = None
    ) -> None:
        self.pages = pages
        self.page_size = page_size
        self.clock = clock or FakeClock()
        self.requests: list[httpx.Request] = []
        self.request_times: list[float] = []
        self.maxlag_first = 0
        self.api_429_first = 0
        self.retry_after = 2
        self.thumb_status: int | None = None
        self.thumb_body: bytes | None = None
        self.quirky_continuations = False
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.request_times.append(self.clock.now())
        headers = {"Retry-After": str(self.retry_after)}
        if request.url.host == "upload.wikimedia.org":
            index = next(
                (
                    i
                    for i, p in enumerate(self.pages)
                    if p.get("imageinfo", [{}])[0].get("thumburl") == str(request.url)
                ),
                0,
            )
            return httpx.Response(
                self.thumb_status or 200,
                content=self.thumb_body if self.thumb_body is not None else make_image_bytes(index),
                headers={
                    **headers,
                    "Content-Type": "image/jpeg" if self.thumb_body is None else "text/html",
                },
            )
        if self.maxlag_first:
            self.maxlag_first -= 1
            return httpx.Response(200, json={"error": {"code": "maxlag"}}, headers=headers)
        if self.api_429_first:
            self.api_429_first -= 1
            return httpx.Response(429, headers=headers)
        offset = int(request.url.params.get("offset", "0"))
        # Copy so the fake's incomplete batches never mutate the full metadata fixture.
        import copy

        pages = copy.deepcopy(self.pages[offset : offset + self.page_size])
        if self.quirky_continuations:
            if offset == 0 and pages:
                pages[0].get("imageinfo", [{}])[0].pop("extmetadata", None)
            elif offset:
                pages.insert(0, {"title": self.pages[offset - 1]["title"]})
                pages.append(
                    {
                        "title": self.pages[0]["title"],
                        "imageinfo": [
                            {"extmetadata": self.pages[0]["imageinfo"][0]["extmetadata"]}
                        ],
                    }
                )
        response: dict[str, Any] = {"query": {"pages": pages}}
        if offset + self.page_size < len(self.pages):
            response["continue"] = {"continue": "x", "offset": offset + self.page_size}
        return httpx.Response(200, json=response)

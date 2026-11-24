from contextlib import suppress
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class _Images(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.urls: list[str] = []

    def _add(self, value: str | None) -> None:
        if not value:
            return
        url = urljoin(self.base_url, value.strip())
        if urlsplit(url).scheme in {"http", "https"} and url not in self.urls:
            self.urls.append(url)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and values.get("property", "") == "og:image":
            self._add(values.get("content"))
        elif tag == "img":
            self._add(values.get("src"))
            self._add(values.get("data-src"))
            srcset = values.get("srcset")
            if srcset:
                candidates: list[tuple[float, str]] = []
                last = ""
                for entry in srcset.split(","):
                    bits = entry.split()
                    if not bits:
                        continue
                    last = bits[0]
                    if len(bits) > 1 and bits[1].endswith("w"):
                        with suppress(ValueError):
                            candidates.append((float(bits[1][:-1]), last))
                self._add(max(candidates)[1] if candidates else last)
        elif tag == "a":
            href = values.get("href")
            if href and urlsplit(href).path.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".avif", ".tif", ".tiff", ".gif", ".bmp")
            ):
                self._add(href)


def extract_image_urls(html: str, base_url: str) -> list[str]:
    parser = _Images(base_url)
    parser.feed(html)
    return parser.urls

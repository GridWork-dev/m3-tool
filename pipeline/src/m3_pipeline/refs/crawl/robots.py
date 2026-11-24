from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


class _RobotsParser(RobotFileParser):
    # The runtime exposes these status flags; typeshed omits them.
    allow_all: bool
    disallow_all: bool


def parse_robots(status: int, body: str) -> RobotFileParser:
    parser = _RobotsParser()
    if status in {404, 410}:
        parser.allow_all = True
    elif status != 200:
        parser.disallow_all = True
    else:
        parser.parse(body.splitlines())
    return parser


class RobotsCache:
    def __init__(self, http: httpx.Client, user_agent: str) -> None:
        self.http = http
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser] = {}

    def _parser(self, url: str) -> RobotFileParser:
        parsed = urlsplit(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._cache:
            try:
                response = self.http.get(
                    f"{host}/robots.txt", headers={"User-Agent": self.user_agent}
                )
                parser = parse_robots(response.status_code, response.text)
            except httpx.HTTPError:
                parser = parse_robots(503, "")
            self._cache[host] = parser
        return self._cache[host]

    def allowed(self, url: str) -> bool:
        return self._parser(url).can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        delay = self._parser(url).crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None

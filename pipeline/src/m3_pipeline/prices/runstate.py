import json
import os
import tempfile
from datetime import date
from pathlib import Path

from pydantic import BaseModel


class _Row(BaseModel):
    url: str
    day: date


class RunState:
    """JSON-lines records in last-run.json, with the refs skip-log torn-tail rules."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._dates: dict[str, date] = {}
        if not path.exists():
            return
        lines = path.read_bytes().splitlines(keepends=True)
        for number, line in enumerate(lines, 1):
            try:
                row = _Row.model_validate_json(line)
            except ValueError:
                # Only invalid JSON in an unterminated last line is a torn append.
                try:
                    json.loads(line)
                except ValueError, UnicodeDecodeError:
                    if number == len(lines) and not line.endswith(b"\n"):
                        path.write_bytes(b"".join(lines[:-1]))
                        break
                raise ValueError(f"{path}:{number}: corrupt run-state record") from None
            self._dates[row.url] = max(self._dates.get(row.url, row.day), row.day)

    def fetched_this_week(self, url: str, today: date) -> bool:
        return url in self._dates and (today - self._dates[url]).days < 7

    def mark(self, url: str, day: date) -> None:
        self._dates[url] = day

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as out:
                for url, day in sorted(self._dates.items()):
                    out.write(json.dumps({"url": url, "day": day.isoformat()}) + "\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

from dataclasses import dataclass, field
from decimal import Decimal

from m3_pipeline.prices.models import Observation


@dataclass
class CheckReport:
    checked: int = 0
    skipped_this_week: int = 0
    blocked: list[str] = field(default_factory=list[str])
    disallowed: list[str] = field(default_factory=list[str])
    failed: list[str] = field(default_factory=list[str])
    flagged: list[str] = field(default_factory=list[str])
    images_added: int = 0
    unblock_used: dict[str, int] = field(default_factory=dict[str, int])
    observations: list[Observation] = field(default_factory=list[Observation])
    previous: dict[str, Decimal] = field(default_factory=dict[str, Decimal])

    def units_line(self) -> str:
        units = {
            "brightdata": "unlocker requests",
            "browserbase": "sessions",
            "evomi": "GB",
            "exa": "searches",
        }
        return "Ledger units: " + ", ".join(
            f"{service} {self._units(service)} {unit}" for service, unit in units.items()
        )

    def render(self) -> str:
        rows = [
            ("checked", self.checked),
            ("skipped this week", self.skipped_this_week),
            ("blocked", len(self.blocked)),
            ("disallowed", len(self.disallowed)),
            ("failed", len(self.failed)),
            ("flagged", len(self.flagged)),
            ("images added", self.images_added),
        ]
        details: list[str] = []
        for name in ("blocked", "disallowed", "failed", "flagged"):
            values: list[str] = getattr(self, name)
            details.extend(f"{name}: {value}" for value in values)
        from m3_pipeline.prices.fetch.brightdata import redact

        return redact(
            "\n".join(
                [
                    "| Result | Count |",
                    "| --- | ---: |",
                    *(f"| {name} | {count} |" for name, count in rows),
                    *details,
                    self.units_line(),
                ]
            )
        )

    def _units(self, service: str) -> int | Decimal:
        value = self.unblock_used.get(service, 0)
        # Evomi is byte-metered, unlike the request/session counters of the other vendors.
        return Decimal(value) / 1_000_000_000 if service == "evomi" else value

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Observation:
    part_id: str
    option_id: str | None
    url: str
    seller: str
    amount: Decimal
    currency: str
    checked: date

    def to_yaml(self) -> dict[str, str | float]:
        return {
            "amount": float(self.amount),
            "currency": self.currency,
            "seller": self.seller,
            "checked": self.checked.isoformat(),
            "url": self.url,
        }

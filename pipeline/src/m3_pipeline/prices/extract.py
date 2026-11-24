import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from m3_pipeline.prices.config import SellerConfig
from m3_pipeline.refs.crawl.blocked import is_blocked


@dataclass(frozen=True)
class ExtractedPrice:
    amount: Decimal
    currency: str


def _money(text: str, currency: str, *, numeric: bool = False) -> Decimal | None:
    markers = {
        "USD": r"(?:US\$|USD|\$)",
        "CAD": r"(?:CA\$|CAD|C\$)",
        "EUR": r"(?:EUR|€)",
        "GBP": r"(?:GBP|£)",
    }
    marker = markers.get(currency)
    if marker is None:
        return None
    if re.search(r"\b(from|shipping|delivery|starting|monthly|installment)\b", text, re.I):
        return None
    number = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)"
    match = re.fullmatch(rf"\s*{marker}\s*{number}\s*", text, re.I)
    if match is None:
        match = re.fullmatch(rf"\s*{number}\s*{marker}\s*", text, re.I)
    if match is None and numeric:
        match = re.fullmatch(rf"\s*{number}\s*", text)
    if match is None:
        return None
    amount = Decimal(match[1].replace(",", ""))
    return amount if amount > 0 else None


def _candidate(node: Any, currency: str) -> Decimal | None:
    # Third-party selector objects are confined to this boundary.
    ancestor = node
    while ancestor is not None and ancestor.tag not in {"body", "html"}:
        attrs = " ".join(str(ancestor.attrib.get(k, "")) for k in ("class", "id", "aria-label"))
        if re.search(r"shipping|delivery|related|recommend|installment|starting", attrs, re.I):
            return None
        ancestor = ancestor.parent
    text = str(node.get_all_text(separator=" ", strip=True)).strip()
    if re.search(r"\b(from|shipping|starting)\b", text, re.I):
        return None
    content = str(node.attrib.get("content", ""))
    return _money(content or text, currency, numeric=bool(content))


def extract_price(
    html: str, seller: SellerConfig, *, storage_dir: Path | None
) -> ExtractedPrice | None:
    if is_blocked(200, "", html[:4096]):
        return None
    from scrapling.parser import Selector

    storage_args: dict[str, str] = {}
    if storage_dir:
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_args = {
            "storage_file": str(storage_dir / f"{seller.id}.db"),
            "url": seller.base_url,
        }
    parser = cast(Any, Selector)(
        html,
        url=seller.base_url,
        adaptive=storage_dir is not None,
        storage_args=storage_args or None,
    )
    hints = seller.price_selectors or (
        '[itemprop="price"]',
        ".price",
        'meta[property="product:price:amount"]',
    )
    for adaptive in (False, True):
        for hint in hints:
            identifier = f"{seller.id}:{hint}"
            for node in parser.css(
                hint, identifier=identifier, adaptive=adaptive and bool(storage_dir)
            ):
                amount = _candidate(node, seller.currency)
                if amount is not None:
                    if storage_dir:
                        # Save only validated prices, never a rejected shipping/related match.
                        parser.save(node._root, identifier)
                    return ExtractedPrice(amount, seller.currency)
    return None

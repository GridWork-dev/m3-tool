import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from m3_pipeline.prices.check import PartRow, PriceRow, load_parts
from m3_pipeline.prices.models import Observation
from m3_pipeline.prices.report import CheckReport


@dataclass(frozen=True)
class PriceChange:
    observation: Observation
    before: Decimal | None


@dataclass
class ApplyResult:
    changed_files: list[Path] = field(default_factory=list[Path])
    changes: list[PriceChange] = field(default_factory=list[PriceChange])
    dry_run: bool = False


def _get(mapping: MappingNode, key: str) -> tuple[ScalarNode, Node] | None:
    for k, v in mapping.value:
        if isinstance(k, ScalarNode) and k.value == key:
            return k, v
    return None


def _target(root: MappingNode, option_id: str | None) -> MappingNode:
    if option_id is None:
        return root
    options = _get(root, "options")
    if options and isinstance(options[1], SequenceNode):
        for node in options[1].value:
            if isinstance(node, MappingNode):
                entry = _get(node, "id")
                if entry and isinstance(entry[1], ScalarNode) and entry[1].value == option_id:
                    return node
    raise ValueError(f"unknown option: {option_id}")


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _replace_prices(text: str, option_id: str | None, prices: list[dict[str, str | float]]) -> str:
    root: object = cast(Any, yaml).compose(text)
    if not isinstance(root, MappingNode):
        raise ValueError("part must be a YAML mapping")
    target = _target(root, option_id)
    existing = _get(target, "prices")
    if existing:
        key, value = existing
        indent = key.start_mark.column
        start = _line_start(text, key.start_mark.index)
        end = value.end_mark.index
        # Collection marks include trailing comments; keep those with the following keys.
        tail = text[start:end].splitlines(keepends=True)
        while tail and (not tail[-1].strip() or tail[-1].lstrip().startswith("#")):
            end -= len(tail.pop())
    else:
        indent = target.value[0][0].start_mark.column
        start = end = _line_start(text, target.end_mark.index)
        if target.end_mark.index == len(text):
            start = end = len(text)
    block = "prices:\n" + "".join(
        "  " + line if line.strip() else line
        for line in yaml.safe_dump(prices, sort_keys=False).splitlines(True)
    )
    block = "".join(
        " " * indent + line if line.strip() else line for line in block.splitlines(True)
    )
    prefix = text[:start]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + block + text[end:]


def _price_dict(row: PriceRow) -> dict[str, str | float]:
    value: dict[str, str | float] = {
        "amount": float(row.amount),
        "currency": row.currency,
        "seller": row.seller,
        "checked": row.checked.isoformat(),
    }
    if row.url:
        value["url"] = row.url
    return value


def _write(path: Path, text: str) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, path.stat().st_mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def apply_observations(
    parts_dir: Path, report: CheckReport, *, dry_run: bool = False
) -> ApplyResult:
    result = ApplyResult(dry_run=dry_run)
    parts = {part.id: (path, part) for path, part in load_parts(parts_dir)}
    groups: dict[tuple[str, str | None], list[Observation]] = defaultdict(list[Observation])
    for observation in report.observations:
        groups[(observation.part_id, observation.option_id)].append(observation)
    pending: dict[Path, str] = {}
    for (part_id, option_id), observations in groups.items():
        if part_id not in parts:
            raise ValueError(f"unknown part: {part_id}")
        path, part = parts[part_id]
        prices = (
            part.prices
            if option_id is None
            else next((o.prices for o in part.options if o.id == option_id), None)
        )
        if prices is None:
            raise ValueError(f"{path}: unknown option: {option_id}")
        rows = list(prices)
        changed = False
        for obs in observations:
            if not obs.amount.is_finite() or obs.amount <= 0:
                raise ValueError(f"{path}: price amount must be positive and finite")
            previous = max(
                (p for p in rows if p.seller == obs.seller and p.currency == obs.currency),
                key=lambda p: p.checked,
                default=None,
            )
            if previous:
                age = (obs.checked - previous.checked).days
                if age < 0:
                    raise ValueError(f"{path}: observation predates latest seller price")
                if previous.amount == obs.amount and age < 7:
                    continue
            rows.append(PriceRow.model_validate(obs.to_yaml()))
            result.changes.append(PriceChange(obs, previous.amount if previous else None))
            changed = True
        if changed:
            text = _replace_prices(
                pending.get(path, path.read_text()), option_id, [_price_dict(p) for p in rows]
            )
            # Catch malformed surgical splices before any file is written.
            PartRow.model_validate(yaml.safe_load(text))
            pending[path] = text
    for path, text in pending.items():
        result.changed_files.append(path)
        if not dry_run:
            _write(path, text)
    return result

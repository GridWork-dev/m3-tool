import json
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from pydantic import ValidationError

from m3_pipeline.refs.models import ImageRecord, Labels, View
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.subjects import parse_subject


class LabelLine(Labels):
    id: str


class LabelImportError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass(frozen=True)
class ExportResult:
    directory: Path
    batches: list[Path]
    images: int


def export_batches(
    store: RefStore,
    subject: str,
    *,
    batch_size: int = 40,
    out_dir: Path | None = None,
) -> ExportResult:
    parse_subject(subject)
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    directory = out_dir or store.work_dir / "refs/classify" / subject
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob("batch-*.json"):
        path.unlink()
    (directory / "CLASSIFY.md").unlink(missing_ok=True)
    candidates = sorted(
        (r for r in store.records(subject) if r.status == "new"), key=lambda r: r.id
    )
    count = (len(candidates) + batch_size - 1) // batch_size
    batches: list[Path] = []
    for index in range(count):
        path = directory / f"batch-{index + 1:03d}.json"
        path.write_text(
            json.dumps(
                {
                    "subject": subject,
                    "batch": index + 1,
                    "of": count,
                    "images": [
                        {"id": r.id, "path": str(store.image_path(r).resolve())}
                        for r in candidates[index * batch_size : (index + 1) * batch_size]
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        batches.append(path)
    (directory / "CLASSIFY.md").write_text(render_classify_md(subject))
    return ExportResult(directory, batches, len(candidates))


def render_classify_md(subject: str) -> str:
    schema = Labels.model_json_schema()
    properties = schema["properties"]
    table = "\n".join(f"| {name} | `{json.dumps(shape)}` |" for name, shape in properties.items())
    example = {
        "id": "a" * 64,
        "generation": "unknown",
        "body": "unknown",
        "market": "unknown",
        "stock": None,
        "view": "other",
        "drive_side": "unknown",
        "trim": "unknown",
        "occlusion": "none",
        "quality": 1,
        "seat": "unknown",
        "notes": "",
    }
    return f"""# Classify {subject}

Read each batch-<batch>.json and open each absolute image path with image access.
Write one JSON object per image, one per line, to labels-<batch>.jsonl next to the
batch file (batch-001.json produces labels-001.jsonl). Include id and every required
label field. No commentary or Markdown in the output file.

| Field | Schema / allowed values |
| --- | --- |
{table}

Views: {", ".join(get_args(View))}.

Use unknown rather than guess. stock is null when it cannot be told. Judge only
what is visible, never the file name. quality ranges from 1 (unusable) to 5 (sharp,
well lit, unobstructed). drive_side is lhd or rhd from where the steering wheel
sits; use unknown without a visible wheel or other unmistakable cue.
seat is only meaningful for interior_seats: driver, passenger or both names the
seat's role, never its side. interior_gauges is a tight instrument-cluster close-up;
a wider dash shot is interior_dash. trim is standard, csl, cs or gtr from visible
cues only: a CSL has a carbon roof, ducktail trunk lid and single-intake front
bumper. Use unknown rather than guess. Put notable aftermarket parts in notes.

Example line:
```json
{json.dumps(example)}
```

Full label schema:
```json
{json.dumps(schema, indent=2)}
```
"""


@dataclass(frozen=True)
class LabelImportResult:
    labeled: int
    relabeled: int


def import_labels(store: RefStore, path: Path) -> LabelImportResult:
    errors: list[str] = []
    seen: set[str] = set()
    updates: dict[str, ImageRecord] = {}
    labeled = relabeled = 0
    for number, text in enumerate(path.read_text().splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = LabelLine.model_validate_json(text)
        except ValidationError as exc:
            errors.append(f"line {number}: {exc}")
            continue
        record = store.get(line.id)
        if record is None:
            errors.append(f"line {number}: unknown id {line.id}")
        elif line.id in seen:
            errors.append(f"line {number}: repeated id {line.id}")
        else:
            labels = Labels.model_validate(line.model_dump(exclude={"id"}))
            updates[line.id] = record.model_copy(
                update={
                    "labels": labels,
                    "status": "duplicate" if record.status == "duplicate" else "labeled",
                }
            )
            if record.labels is None:
                labeled += 1
            else:
                relabeled += 1
        seen.add(line.id)
    if errors:
        raise LabelImportError(errors)
    store.update(updates.get(r.id, r) for r in store.records())
    return LabelImportResult(labeled, relabeled)

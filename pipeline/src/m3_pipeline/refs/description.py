from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.refs.subjects import parse_subject


class DescriptionError(ValueError):
    pass


class _Dimensions(BaseModel):
    lengthMm: int
    widthMm: int
    heightMm: int
    wheelbaseMm: int
    trackFrontMm: int
    trackRearMm: int


class _Engine(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str


class _Generation(BaseModel):
    id: str
    name: str
    chassis: str
    years: list[int]
    engines: list[_Engine]
    bodies: list[str]
    dimensions: dict[str, _Dimensions]


class _Option(BaseModel):
    id: str
    label: str
    attributes: dict[str, object] = {}


class _Part(BaseModel):
    id: str
    name: str
    brand: str | None = None
    category: str
    attributes: dict[str, object] = {}
    options: list[_Option] = []


def _read[T: BaseModel](path: Path, model: type[T]) -> T:
    try:
        data = cast(object, yaml.safe_load(path.read_text()))
        return model.model_validate(data)
    except OSError as exc:
        raise DescriptionError(f"{path}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise DescriptionError(f"{path}: invalid YAML: {exc}") from exc
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(k) for k in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise DescriptionError(f"{path}: {errors}") from exc


def _engine_text(engine: _Engine) -> str:
    values = engine.model_dump(exclude={"code"})
    extras = [
        f"{key} {value}"
        for key, value in sorted(values.items())
        if isinstance(value, (str, int, float, bool))
    ]
    return engine.code + (f" ({', '.join(extras)})" if extras else "")


def _attributes(values: dict[str, object]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in sorted(values.items()))


def build_description(spec: AssetSpec, settings: Settings) -> str:
    subject = parse_subject(spec.subject)
    checklist: list[str] = []
    if subject.kind == "product":
        path = settings.repo_root / "data/parts" / spec.generation / f"{subject.part_id}.yaml"
        part = _read(path, _Part)
        prompt = f"{part.brand + ' ' if part.brand else ''}{part.name}, category {part.category}."
        if part.attributes:
            prompt += f" {_attributes(part.attributes)}."
        checklist.extend(f"{key}: {value}" for key, value in sorted(part.attributes.items()))
        for option in part.options:
            details = f": {_attributes(option.attributes)}" if option.attributes else ""
            checklist.append(option.label + details)
    else:
        path = settings.repo_root / "data/generations" / f"{spec.generation}.yaml"
        generation = _read(path, _Generation)
        body = subject.body
        if body not in generation.bodies or body not in generation.dimensions:
            raise DescriptionError(f"{path}: missing body or dimensions for {body}")
        dimensions = generation.dimensions[body].model_dump()
        measures = [
            f"{key}: {value} mm ({value / 1000:.3f} m)" for key, value in dimensions.items()
        ]
        engines = "; ".join(_engine_text(engine) for engine in generation.engines)
        years = "–".join(str(year) for year in generation.years)
        prompt = (
            f"{generation.name} ({generation.chassis}) {body}, {years}, "
            f"US-spec, left-hand drive. Engines: {engines}. {'; '.join(measures)}."
        )
        checklist.append(f"Body style: {body}")
        checklist.extend(f"{measure}, within 1%" for measure in measures)
        checklist.append("Stock appearance")
        checklist.append("Wheels are placeholders the pipeline replaces")
        if subject.kind == "interior":
            components = (
                "dash with gauge cluster, steering wheel, seats, door cards, center console"
            )
            prompt += (
                f" Left-hand-drive cabin: {components}; no roundel on the steering wheel or gauges."
            )
            checklist.extend(
                [components, "Left-hand-drive cabin", "no roundel on the steering wheel or gauges"]
            )
    checklist.append("No manufacturer badges, logos or roundels")
    text = (
        f"# {spec.subject} reference description\n\n## Generator prompt\n\n{prompt}\n\n"
        "## Critic checklist\n\n" + "\n".join(f"- [ ] {line}" for line in checklist) + "\n"
    )
    notes = settings.repo_root / "pipeline/descriptions" / f"{spec.subject}.md"
    if notes.exists():
        text += "\n## Notes (hand-written)\n\n" + notes.read_text()
    return text

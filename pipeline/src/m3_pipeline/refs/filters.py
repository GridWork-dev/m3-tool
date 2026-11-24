from dataclasses import dataclass

from m3_pipeline.refs.models import Body, ImageRecord, Kind, Trim
from m3_pipeline.refs.subjects import parse_subject


@dataclass(frozen=True)
class FilterTarget:
    kind: Kind
    generation: str | None
    body: Body | None
    trim: Trim | None = None

    @classmethod
    def from_subject(cls, subject: str) -> FilterTarget:
        ref = parse_subject(subject)
        return cls(
            ref.kind, ref.generation, ref.body, None if ref.kind == "product" else "standard"
        )


@dataclass(frozen=True)
class FilterDecision:
    accepted: bool
    reasons: tuple[str, ...]


def evaluate(record: ImageRecord, target: FilterTarget) -> FilterDecision:
    labels = record.labels
    if labels is None:
        return FilterDecision(False, ("unlabeled",))
    reasons: list[str] = []
    if record.status == "duplicate":
        reasons.append("duplicate")
    view = labels.view
    family = {
        "base-car": view in {"front", "rear", "top"} or view.startswith("side_") or "_34_" in view,
        "interior": view.startswith("interior_"),
        "product": view.startswith("product_"),
    }
    if not family[target.kind]:
        reasons.append("wrong_view_family")
    if target.kind != "product":
        if labels.stock is False:
            reasons.append("modified")
        if labels.generation != target.generation:
            reasons.append("wrong_generation")
        if target.trim is not None and labels.trim not in {target.trim, "unknown"}:
            reasons.append("trim")
    if target.kind == "base-car":
        if labels.body != target.body:
            reasons.append("wrong_body")
        if labels.occlusion == "major":
            reasons.append("major_occlusion")
    return FilterDecision(not reasons, tuple(reasons))

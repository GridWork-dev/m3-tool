from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.refs.description import DescriptionError, build_description
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.subjects import parse_subject
from m3_pipeline.refs.viewsets import INTERIOR_ORDER, ViewsetPolicy, write_viewset
from m3_pipeline.stages import StageResult, register


@register("refs")
def refs_stage(spec: AssetSpec, settings: Settings) -> StageResult:
    try:
        subject = parse_subject(spec.subject)
    except ValueError as exc:
        return StageResult(False, [str(exc)], [])
    if subject.kind != spec.kind:
        return StageResult(
            False, [f"subject kind {subject.kind} differs from asset kind {spec.kind}"], []
        )
    directory = settings.work_dir / "assets" / spec.id / "refs"
    policy = ViewsetPolicy()
    vs = write_viewset(RefStore(settings), spec.subject, directory / "viewset.json", policy=policy)
    description_path = directory / "description.md"
    messages: list[str] = []
    description_ok = True
    try:
        description = build_description(spec, settings)
    except DescriptionError as exc:
        description_ok = False
        messages.append(str(exc))
        description = f"# {spec.subject} reference description\n\nDescription error: {exc}\n"
    description_path.write_text(description)
    if subject.kind == "interior":
        complete = all(
            len(vs.components.get(component, [])) >= policy.min_views
            for component in INTERIOR_ORDER
        )
    else:
        complete = len(vs.views) >= policy.min_views
    if vs.missing:
        messages.append(f"missing: {', '.join(vs.missing)}")
    for reason, count in sorted(vs.rejected.items()):
        messages.append(f"rejected {reason}={count}")
    for entry in vs.entries():
        if entry.contains_text_risk:
            messages.append(f"{entry.view}: mirrored RHD image, text may be reversed")
    return StageResult(
        description_ok and complete, messages, [directory / "viewset.json", description_path]
    )

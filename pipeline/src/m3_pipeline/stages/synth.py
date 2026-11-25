"""Reference synthesis. Review and provenance gates apply before every remote image call."""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from m3_pipeline.assets import ID_PATTERN, AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import StageResult, register
from m3_pipeline.stages.lib.codex import CodexError, run_codex
from m3_pipeline.stages.lib.critic import Verdict, run_critic
from m3_pipeline.stages.lib.dims import load_dimensions
from m3_pipeline.stages.lib.fal import CallResult, FalClient, FalError, PlannedCall
from m3_pipeline.stages.lib.generators import load_generators
from m3_pipeline.stages.lib.inputs import (
    ensure_reviewed,
    load_redactions,
    prepare_image,
    propose_redactions,
    save_redactions,
    validate_redaction_orientation,
)
from m3_pipeline.stages.lib.paths import (
    require_outside_repo,
    require_write_target_outside_repo,
    stage_dir,
    subject_body,
)
from m3_pipeline.stages.lib.provenance import (
    ViewProvenance,
    check_provenance,
    load_provenance,
    write_provenance,
)
from m3_pipeline.stages.lib.spend import SpendDenied
from m3_pipeline.stages.lib.viewset_io import ViewRef, load_viewset, require_generator_inputs

VIEWS = frozenset({"front", "side", "rear", "front_34", "rear_34"})
PROMPT = """Create one faithful reference view of one car: the E46 M3 coupe, US-spec, stock.
View: {view}. Plain light-gray seamless background. Show the whole car with at least
5% margin on every side. No number plate: use a blank body-color panel. No badges,
roundel or logos. Keep the proportions of the reference photos. Every side and
three-quarter view shows the car's left side. In the side view the nose points to
the left of the image. Save the image as {view}.png in the working directory.
"""
_ANGLES = {
    "front": 0,
    "front_34": 45,
    "side": 90,
    "rear_34": 135,
    "rear": 180,
    "front_34_left": 45,
    "front_34_right": -45,
    "side_left": 90,
    "side_right": -90,
    "rear_34_left": 135,
    "rear_34_right": -135,
}


@dataclass(frozen=True)
class ViewPlan:
    inputs: tuple[str, ...]
    engine: Literal["codex", "fal"]
    extra: str
    call_id: str | None
    options: dict[str, object]


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in cast(dict[object, object], value)
    ):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in cast(list[object], value)
    ):
        raise ValueError(f"{label} must be a list of strings")
    result = tuple(cast(list[str], value))
    if len(set(result)) != len(result):
        raise ValueError(f"{label} repeats a value")
    return result


def _plan(
    path: Path,
) -> tuple[dict[str, ViewPlan], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if not path.is_file():
        raise ValueError(f"{path} does not exist; write synth/plan.json first")
    body = _object(json.loads(path.read_text()), "synth plan")
    if set(body) - {"views", "reviewed_inputs", "force", "fallback"}:
        raise ValueError("synth plan has unknown keys")
    raw = _object(body.get("views"), "views")
    if not raw or set(raw) - VIEWS:
        raise ValueError("views must name front, side, rear, front_34 or rear_34")
    views: dict[str, ViewPlan] = {}
    for name, value in raw.items():
        entry = _object(value, name)
        if set(entry) - {"inputs", "engine", "prompt_extra", "call_id", "options"}:
            raise ValueError(f"{name} has unknown keys")
        inputs = _strings(entry.get("inputs"), f"{name}.inputs")
        engine, extra = entry.get("engine", "codex"), entry.get("prompt_extra", "")
        call_id = entry.get("call_id")
        if not inputs or engine not in ("codex", "fal") or not isinstance(extra, str):
            raise ValueError(f"{name}: inputs, engine or prompt_extra is invalid")
        if call_id is not None and (
            not isinstance(call_id, str) or not ID_PATTERN.fullmatch(call_id)
        ):
            raise ValueError(f"{name}.call_id must be a nonempty string")
        views[name] = ViewPlan(
            inputs,
            engine,
            extra,
            call_id,
            _object(entry.get("options", {}), "options"),
        )
    reviewed = _strings(body.get("reviewed_inputs", []), "reviewed_inputs")
    force = _strings(body.get("force", []), "force")
    fallback = _strings(body.get("fallback", []), "fallback")
    for label, names in (("force", force), ("fallback", fallback)):
        if set(names) - set(views):
            raise ValueError(f"{label} must list known views in this plan")
    return views, reviewed, force, fallback


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nearest(name: str, refs: list[ViewRef]) -> list[ViewRef]:
    def distance(ref: ViewRef) -> float:
        angle = _ANGLES.get(ref.view, 0)
        delta = abs(_ANGLES[name] - angle) % 360
        return min(delta, 360 - delta)

    return sorted(refs, key=distance)[:2]


def _harvest(
    cwd: Path, view: str, message: str, settings: Settings, *, old_pngs: set[Path] | None = None
) -> Path:
    from PIL import Image

    expected = cwd / f"{view}.png"
    candidates = [expected] if expected.is_file() else []
    if not candidates:
        # Last messages commonly use Markdown links or backticks around absolute paths.
        candidates = [Path(match) for match in re.findall(r"(/[^\n`\"<>]*?\.png)", message)]
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        candidates = [path for path in cwd.glob("*.png") if path not in (old_pngs or set())]
    if len(candidates) != 1:
        raise ValueError(f"{view}: expected one generated PNG; found {len(candidates)}")
    path = candidates[0]
    require_outside_repo(repo_root=settings.repo_root, path=path)
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError(f"{view}: generated file is not a PNG")
        image.verify()
    return path


def _invalidate(root: Path, view: str, items: list[ViewProvenance]) -> list[ViewProvenance]:
    if view == "side":
        (root / "proportion.json").unlink(missing_ok=True)
    approval = root / "approved.json"
    if approval.exists():
        body = _object(json.loads(approval.read_text()), "approved.json")
        approved = _object(body.get("views"), "approved views")
        approved.pop(view, None)
        approval.write_text(json.dumps(body, indent=2) + "\n")
    items = [item for item in items if item.view != view]
    write_provenance(root / "provenance.json", items)
    return items


def _proportion_failed(root: Path) -> bool:
    try:
        body = _object(json.loads((root / "proportion.json").read_text()), "proportion")
        return body.get("ok") is False and body.get("side_sha256") == _digest(
            root / "views/side.png"
        )
    except OSError, ValueError:
        return False


def _visual_verdict(verdict: Verdict) -> bool | None:
    """Infrastructure and malformed answers are unknown, never visual rejections."""
    if any(
        issue.text.startswith(("codex critic failed:", "critic returned no valid verdict"))
        for issue in verdict.issues
    ):
        return None
    return verdict.ok


def _paid_result(
    client: FalClient, call: PlannedCall, out_dir: Path, settings: Settings
) -> CallResult:
    """A durable intent permits one submit only. Subsequent runs recover or resume.

    Even a crash between intent creation and submission is ambiguous: resume fails closed
    instead of guessing that no request was sent. The operator can inspect the call journal.
    """
    intent = out_dir / "intent.json"
    for path in (out_dir, intent):
        require_write_target_outside_repo(dest=path, repo_root=settings.repo_root)
    fingerprint = {
        "generator": call.generator,
        "slots": list(call.slots),
        "options": dict(call.options),
        "images": [_digest(path) for path in call.images],
    }
    serialized = json.dumps(fingerprint, sort_keys=True)
    if intent.exists():
        if intent.read_text() != serialized:
            raise ValueError(
                f"{call.call_id}: call_id was already used for different inputs/options"
            )
        result = client.completed(call.call_id, out_dir)
        return result if result is not None else client.resume(call.call_id, out_dir)
    client.preflight(call, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents two invocations from both submitting this call id.
    with intent.open("x") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        return client.run(call, out_dir)
    except SpendDenied:
        # Authorization happens before submission. A rejected cap/ledger can safely be
        # corrected and retried; only ambiguous execution retains the no-resubmit intent.
        intent.unlink()
        raise


@register("synth")
def synth(asset: AssetSpec, settings: Settings) -> StageResult:
    outputs: list[Path] = []
    messages: list[str] = []
    try:
        root = stage_dir(settings, asset.id, "synth").resolve()
        plans, reviewed, force, fallback = _plan(root / "plan.json")
        viewset = load_viewset(settings.work_dir, asset.subject)
        refs = {ref.image_id: ref for ref in viewset.entries()}
        for name, plan in plans.items():
            if set(plan.inputs) - refs.keys():
                raise ValueError(
                    f"{name}: unknown input image ids: {set(plan.inputs) - refs.keys()}"
                )
        # The critic sees real references too: those uploads need the very same privacy gate.
        needed = set(image_id for plan in plans.values() for image_id in plan.inputs)
        nearest = {name: _nearest(name, viewset.entries()) for name in plans}
        needed.update(ref.image_id for pair in nearest.values() for ref in pair)
        selected = [ref for image_id, ref in refs.items() if image_id in needed]
        for ref in selected:
            require_outside_repo(repo_root=settings.repo_root, path=ref.image_path)
        inputs = stage_dir(settings, asset.id, "inputs").resolve()
        cache_path = inputs / "redactions.json"
        targets = [
            cache_path,
            inputs / "prepared",
            root / "views",
            root / "provenance.json",
            root / "approved.json",
            root / "proportion.json",
        ]
        targets += [root / "views" / f"{name}.png" for name in plans]
        targets += [inputs / "prepared" / f"{ref.image_id}.png" for ref in selected]
        for target in targets:
            require_write_target_outside_repo(dest=target, repo_root=settings.repo_root)
        boxes = load_redactions(cache_path) if cache_path.exists() else {}
        for ref in selected:
            if ref.image_id not in boxes and ref.page_url:
                from urllib.parse import urlparse

                if urlparse(ref.page_url).hostname == "commons.wikimedia.org":
                    boxes[ref.image_id] = propose_redactions(ref, settings.work_dir, cwd=root)
                    save_redactions(cache_path, boxes, upright_ids=[ref.image_id])
        boxes = load_redactions(cache_path) if cache_path.exists() else {}
        for ref in selected:
            validate_redaction_orientation(ref, cache_path)
        require_generator_inputs(selected, reviewed_ids=reviewed, redacted_ids=boxes.keys())
        prepared = {
            ref.image_id: prepare_image(
                ref, settings.work_dir, inputs / "prepared", boxes[ref.image_id]
            )
            for ref in selected
        }
        ensure_reviewed(list(prepared.values()), reviewed)
        (root / "views").mkdir(exist_ok=True)
        provenance = root / "provenance.json"
        items = load_provenance(provenance) if provenance.exists() else []
        check_provenance(items, viewset)
        description = root.parent / "refs/description.md"
        if description.is_file():
            checklist = [description.read_text()]
        else:
            dims = load_dimensions(
                settings.repo_root, asset.generation, subject_body(asset.subject)
            )
            checklist = [f"Dimensions in mm: {dims}"]
        checklist.append("side views show the left side, nose to the left of the image")
        registry = {}
        for name, plan in plans.items():
            target = root / "views" / f"{name}.png"
            previous = next((item for item in items if item.view == name), None)
            prompt = PROMPT.format(view=name) + plan.extra
            prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
            matches = (
                previous is not None
                and previous.engine == plan.engine
                and previous.inputs == plan.inputs
                and previous.prompt_sha256 == prompt_hash
                and target.is_file()
                and previous.sha256 == _digest(target)
            )
            if (
                name not in force
                and matches
                and previous is not None
                and previous.critic_ok is True
            ):
                messages.append(f"{name}: already exists; use force to regenerate")
                continue
            call_dir = root / "fal" / (plan.call_id or "unplanned")
            if plan.engine == "fal":
                if name not in fallback:
                    raise ValueError(f"{name}: fal fallback must be named in fallback")
                require_write_target_outside_repo(dest=call_dir, repo_root=settings.repo_root)
                intent = call_dir / "intent.json"
                require_write_target_outside_repo(dest=intent, repo_root=settings.repo_root)
                recovering = intent.exists()
                critic_failed = (
                    previous is not None
                    and previous.critic_ok is False
                    and target.is_file()
                    and previous.sha256 == _digest(target)
                )
                if not recovering and not (critic_failed or _proportion_failed(root)):
                    raise ValueError(
                        f"{name}: fal fallback requires a failed critic or proportion guard"
                    )
                registry = load_generators(settings.repo_root / "pipeline/generators.toml")
                if "image-edit" not in registry:
                    raise ValueError("fal fallback requires an image-edit entry in generators.toml")
                if not plan.call_id:
                    raise ValueError(f"{name}: fal fallback requires an explicit call_id")
            prompt = PROMPT.format(view=name) + plan.extra
            paths = [prepared[image_id].path.resolve() for image_id in plan.inputs]
            # Keep old image and guard evidence until a replacement is durably staged.
            import tempfile

            with tempfile.TemporaryDirectory(prefix=f"attempt-{name}-", dir=root) as scratch:
                cwd = Path(scratch)
                last_message = cwd / "last.md"
                for path in (cwd, last_message):
                    require_write_target_outside_repo(dest=path, repo_root=settings.repo_root)
                if plan.engine == "codex":
                    generated = root / f"{name}.png"
                    require_write_target_outside_repo(dest=generated, repo_root=settings.repo_root)
                    generated.unlink(missing_ok=True)
                    old_pngs = set(root.glob("*.png"))
                    message = run_codex(prompt, paths, cwd=root, last_message=last_message)
                    source = _harvest(root, name, message, settings, old_pngs=old_pngs)
                else:
                    gen = registry["image-edit"]
                    slots = tuple(
                        gen.view_slots.get(refs[image_id].view)
                        or (gen.slot_order[index] if index < len(gen.slot_order) else "unknown")
                        for index, image_id in enumerate(plan.inputs)
                    )
                    call = PlannedCall(
                        cast(str, plan.call_id),
                        "image-edit",
                        tuple(paths),
                        slots,
                        None,
                        {**plan.options, "prompt": prompt},
                    )
                    result = _paid_result(FalClient(settings, registry), call, call_dir, settings)
                    pngs = [path for path in result.files.values() if path.suffix.lower() == ".png"]
                    if len(pngs) != 1:
                        raise ValueError(f"{name}: fal did not return exactly one PNG")
                    source = _harvest(call_dir, name, str(pngs[0]), settings)
                staged = target.with_suffix(".pending.png")
                require_write_target_outside_repo(dest=staged, repo_root=settings.repo_root)
                shutil.copyfile(source, staged)
                with staged.open("rb") as stream:
                    os.fsync(stream.fileno())
                # Invalidate only once generation and decoding have succeeded. A paid failure
                # preserves the old failure evidence needed for a safe resumed invocation.
                items = _invalidate(root, name, items)
                staged.replace(target)
            images = [prepared[ref.image_id].path.resolve() for ref in nearest[name]] + [target]
            view_checklist = [*checklist, f"The candidate must show the requested {name} view."]
            verdict = run_critic("synth-view", view_checklist, images, cwd=root)
            item = ViewProvenance(
                name,
                plan.inputs,
                hashlib.sha256(prompt.encode()).hexdigest(),
                plan.engine,
                datetime.now(UTC).isoformat(),
                _digest(target),
                _visual_verdict(verdict),
            )
            items.append(item)
            write_provenance(provenance, items)
            outputs.extend([target, provenance])
            messages.extend(f"{name}: {issue.text}" for issue in verdict.issues)
            if any(
                issue.text.startswith("codex critic failed: codex is not using the ChatGPT login")
                for issue in verdict.issues
            ):
                return StageResult(False, messages, outputs)
        ok = all(
            any(
                item.view == name
                and item.critic_ok is True
                and item.sha256 == _digest(root / "views" / f"{name}.png")
                for item in items
            )
            for name in plans
        )
        return StageResult(
            ok, messages + ["Run proportion and obtain user approval before generation"], outputs
        )
    except (OSError, ValueError, CodexError, FalError, SpendDenied) as error:
        return StageResult(False, messages + [str(error)], outputs)

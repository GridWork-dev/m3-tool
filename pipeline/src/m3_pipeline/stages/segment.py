"""The `segment` stage: split a cleaned candidate into parts, by Tripo or by a Blender script.

`<work_dir>/assets/<id>/segment/plan.json` names what to run:
`{"candidate": "<call id of the generated model>", "method": "tripo" | "scripted",
"call_id": "seg-tripo-01", "reduce_to_triangles": 150000}`. The input is
`cleanup/<candidate>/prepared.glb`, and every output goes under `segment/<candidate>/<method>/`, so
two candidates or two methods never overwrite each other. `call_id` is the spend tag of the paid
call (`tripo` only); `reduce_to_triangles` defaults to 150000. Both methods leave `segmented.glb`
(the split mesh, which `cleanup` requires) and `parts.json` there.

`tripo` makes a copy of the input at about the final budget (`reduce_mesh.py`, so the segmented
output can be used as it is, with no label transfer), sends it to `tripo-segment` through the
guarded client, and saves every file of the result under `raw/`: a paid result is never discarded.
The stage then picks the GLB, `model_urls.glb` when the result offers one and else `model_mesh`
when that is a GLB (files are told apart by their first bytes, not by the extension fal's URL
carried). An FBX-only result is converted by `convert_to_glb.py` in headless Blender before
anything reads it. A result with neither is recorded as `outcome: "unsupported-result"` in
`parts.json`, the stage is not ok, and `raw/` stays.

`scripted` (the free fallback) hands `split_scripted.py` a plan of Blender-frame numbers computed
here from the data and `placement.module_cut_planes`: every box and spatial threshold sits under a
key ending `_blender` (converted through `frames`), and color thresholds carry no suffix. The
thresholds are named constants below; they are estimates that the first real model tunes.

`parts.json` lists each part's name, triangle count and bounding box (the GLB's own frame:
meters, Y up, nose toward -Z) from `part_stats`, the file's totals from `mesh_stats`, and which of
the contract's parts the split found and missed. A split that misses some is a result, not a
failure: the stage stays ok and says what is missing.

A paid call is never repeated and never gets a new tag. The tag comes from `plan.json` only.
`call.json` next to `raw/` records the call. A `FalError` that says it is `resumable` leaves
`{"state": "pending"}`, and so does an interrupt (Ctrl-C) while the call runs; the next run with the
same tag calls `resume`, which never submits. A finished call leaves `{"state": "done"}` and its
file names, and the next run with the same tag reuses those files without calling fal at all, so a
failed conversion or a corrected plan costs nothing. A missing local record is reconciled from
the guarded client's authoritative completed journal before any new call. Any other failure leaves
no record: a new `run` with the same tag is then denied by the spend guard. A new tag needs a
ledger row and a new `call_id` in `plan.json`.
"""

import contextlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import StageResult, register
from m3_pipeline.stages.lib.blender import run_blender
from m3_pipeline.stages.lib.dims import Dimensions, load_dimensions
from m3_pipeline.stages.lib.fal import CallResult, FalClient, FalError, PlannedCall
from m3_pipeline.stages.lib.frames import box_to_blender, contract_to_blender
from m3_pipeline.stages.lib.generators import load_generators
from m3_pipeline.stages.lib.glbmeta import GlbError, mesh_stats, part_stats
from m3_pipeline.stages.lib.paths import (
    require_outside_repo,
    require_write_target_outside_repo,
    stage_dir,
    subject_body,
)
from m3_pipeline.stages.lib.placement import module_cut_planes
from m3_pipeline.stages.lib.spend import SpendDenied

# The parts the contract wants out of a split: the body, the four swappable modules and the
# materials the cleanup stage gives the rest. A split names its parts however it likes (Tripo
# names its own), so a missing one is reported, never fatal.
CONTRACT_PARTS = (
    "body",
    "bumper_front",
    "bumper_rear",
    "trunk_lid",
    "roof",
    "glass",
    "lights_front",
    "lights_rear",
    "trim",
    "grille",
    "undercarriage",
)

_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PLAN_KEYS = frozenset({"candidate", "method", "call_id", "reduce_to_triangles"})
_DEFAULT_TRIANGLES = 150_000  # the contract's upper budget: no label transfer is needed after it
_STDERR_TAIL = 800  # characters of Blender's output kept in a failure message

# The scripted split's thresholds, in the contract frame's words (meters, a share of the car's
# height, a luminance in 0..1) and converted to the Blender frame when the plan is built. All are
# ESTIMATES: the first real model's color-by-part renders tune them.
_UNDERCARRIAGE_NORMAL_UP_MAX = -0.7  # faces whose normal points down: up-component below this
_UNDERCARRIAGE_MAX_HEIGHT_M = 0.35  # and whose centroid sits below this height
_BELT_LINE_HEIGHT_FRACTION = 0.70  # the glass starts here, as a share of the car's height
_END_BAND_M = 0.50  # how far from the nose and tail the lights and the grille can be
_GRILLE_HALF_WIDTH_M = 0.45  # the grille is within this of the centerline
_GRILLE_MAX_HEIGHT_M = 0.85  # and below this height: above the front bumper box (0.70 m)
_DARK_LUMINANCE_MAX = 0.20  # sampled base color at or below this is dark (glass, trim, grille)
_BRIGHT_LUMINANCE_MIN = 0.80  # at or above this is a bright light lens
_RED_MIN = 0.50  # red: the red channel is at least this
_RED_DOMINANCE = 1.8  # and at least this many times the larger of green and blue

Method = Literal["tripo", "scripted"]


class _Failed(Exception):
    """A step of the stage failed: the message is the stage's, and `outputs` are the files worth
    listing (the record of an unsupported result)."""

    def __init__(self, message: str, outputs: Sequence[Path] = ()) -> None:
        super().__init__(message)
        self.outputs = list(outputs)


class _Fal(Protocol):
    """Local recovery and the two guarded network operations the stage uses."""

    def completed(self, call_id: str, out_dir: Path) -> CallResult | None: ...

    def run(self, call: PlannedCall, out_dir: Path) -> CallResult: ...

    def resume(self, call_id: str, out_dir: Path) -> CallResult: ...


def _fal_client(settings: Settings) -> _Fal:
    """The guarded client. Tests replace this name. It gets no journal, session, date or cap:
    the guard reads its own fixed journal and the session from the environment."""
    registry = load_generators(settings.repo_root / "pipeline" / "generators.toml")
    return FalClient(settings, registry)


@dataclass(frozen=True)
class _Plan:
    candidate: str
    method: Method
    call_id: str | None  # the spend tag; `tripo` only
    reduce_to_triangles: int


@dataclass(frozen=True)
class _Job:
    settings: Settings
    asset: AssetSpec
    plan: _Plan
    prepared: Path
    out: Path

    @property
    def segmented(self) -> Path:
        return self.out / "segmented.glb"

    @property
    def parts_json(self) -> Path:
        return self.out / "parts.json"

    @property
    def raw(self) -> Path:
        return self.out / "raw"

    @property
    def call_json(self) -> Path:
        return self.out / "call.json"


@dataclass(frozen=True)
class _Paid:
    files: dict[str, Path]  # result key -> the file under raw/
    cost_usd: str  # what the call was authorized at, as fixed-point text


@dataclass(frozen=True)
class _Record:
    """What `call.json` says: the tag and whether the call finished."""

    call_id: str
    state: Literal["pending", "done"]
    files: dict[str, str]
    cost_usd: str


@register("segment")
def segment(asset: AssetSpec, settings: Settings) -> StageResult:
    try:
        job = _start(asset, settings)
        paid: _Paid | None = None
        if job.plan.method == "scripted":
            _scripted(job)
        else:
            paid = _tripo(job)
            _place_tripo_result(job, paid)
        messages = _write_parts(job, paid)
    except _Failed as failure:
        return StageResult(False, [str(failure)], failure.outputs)
    return StageResult(True, messages, [job.segmented, job.parts_json])


# --- the plan and the paths ---


def _start(asset: AssetSpec, settings: Settings) -> _Job:
    try:
        base = stage_dir(settings, asset.id, "segment")
        plan_file = base / "plan.json"
        require_outside_repo(repo_root=settings.repo_root, path=plan_file)
    except ValueError as error:
        raise _Failed(str(error)) from error
    plan = _read_plan(plan_file)
    prepared = settings.work_dir / "assets" / asset.id / "cleanup" / plan.candidate / "prepared.glb"
    out = base / plan.candidate / plan.method
    try:
        require_outside_repo(repo_root=settings.repo_root, path=prepared)
        require_write_target_outside_repo(dest=out / "parts.json", repo_root=settings.repo_root)
    except ValueError as error:
        raise _Failed(str(error)) from error
    if not prepared.is_file():
        raise _Failed(
            f"{prepared} does not exist: the candidate {plan.candidate!r} has no prepared mesh; "
            "run --stage cleanup (through prepare) for it first"
        )
    job = _Job(settings, asset, plan, prepared, out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        # An earlier run's outputs go first, so a failure below cannot leave a split or a
        # report that `cleanup` would take for this run's.
        for stale in (job.segmented, job.parts_json):
            stale.unlink(missing_ok=True)
    except OSError as error:
        raise _Failed(f"could not prepare {out}: {error}") from error
    return job


def _read_plan(path: Path) -> _Plan:
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        raise _Failed(
            f"{path} does not exist: write the segment plan first "
            '({"candidate", "method", "call_id", "reduce_to_triangles"})'
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise _Failed(f"plan.json could not be read: {error}") from error
    try:
        data: object = json.loads(text)
    except ValueError as error:
        raise _Failed(f"plan.json is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise _Failed("plan.json must hold a JSON object")
    fields = cast("dict[str, object]", data)
    unknown = sorted(set(fields) - _PLAN_KEYS)
    if unknown:
        known = ", ".join(sorted(_PLAN_KEYS))
        raise _Failed(f"plan.json has unknown key(s) {', '.join(unknown)}; known: {known}")
    candidate = fields.get("candidate")
    if not isinstance(candidate, str) or not _ID.fullmatch(candidate):
        raise _Failed(
            "plan.json: candidate must be a call id (lower-case words joined by single hyphens), "
            f"not {candidate!r}"
        )
    method = fields.get("method")
    if method == "tripo":
        call_id = fields.get("call_id")
        if not isinstance(call_id, str) or not _ID.fullmatch(call_id):
            raise _Failed(
                "plan.json: the tripo method needs call_id, the spend tag of its ledger row "
                f"(lower-case words joined by single hyphens), not {call_id!r}"
            )
        chosen: tuple[Method, str | None] = ("tripo", call_id)
    elif method == "scripted":
        chosen = ("scripted", None)  # free: whatever call_id the plan carries is not used
    else:
        raise _Failed(f"plan.json: method must be 'tripo' or 'scripted', not {method!r}")
    triangles = fields.get("reduce_to_triangles", _DEFAULT_TRIANGLES)
    if isinstance(triangles, bool) or not isinstance(triangles, int) or triangles < 1:
        raise _Failed(
            f"plan.json: reduce_to_triangles must be a positive integer, not {triangles!r}"
        )
    return _Plan(candidate, chosen[0], chosen[1], triangles)


# --- scripted ---


def _up(meters: float) -> float:
    """A height or an up-component, in the Blender frame (Z up)."""
    return contract_to_blender((0.0, meters, 0.0))[2]


def _toward_nose(z_contract: float) -> float:
    """A position along the car from a contract-frame z, in the Blender frame (nose at +Y)."""
    return contract_to_blender((0.0, 0.0, z_contract))[1]


def scripted_plan(dims: Dimensions, *, glb: Path, out_dir: Path) -> dict[str, object]:
    """The plan `split_scripted.py` reads. Every spatial number is in the Blender frame under a
    key ending `_blender`, converted here through `frames`; the color thresholds carry no suffix.
    `modules_blender` keeps the order the script applies the module rules in."""
    height = dims.height_mm / 1000
    half_length = dims.length_mm / 2000
    modules: dict[str, object] = {}
    for name, box in module_cut_planes(dims).items():
        in_blender = box_to_blender(box)
        modules[name] = {"min": list(in_blender.min), "max": list(in_blender.max)}
    return {
        "glb": str(glb),
        "out_dir": str(out_dir),
        "modules_blender": modules,
        "undercarriage_normal_z_max_blender": _up(_UNDERCARRIAGE_NORMAL_UP_MAX),
        "undercarriage_z_max_blender": _up(_UNDERCARRIAGE_MAX_HEIGHT_M),
        "belt_line_z_blender": _up(_BELT_LINE_HEIGHT_FRACTION * height),
        "front_band_y_min_blender": _toward_nose(-half_length + _END_BAND_M),
        "rear_band_y_max_blender": _toward_nose(half_length - _END_BAND_M),
        "grille_x_max_blender": _GRILLE_HALF_WIDTH_M,
        "grille_z_max_blender": _up(_GRILLE_MAX_HEIGHT_M),
        "dark_luminance_max": _DARK_LUMINANCE_MAX,
        "bright_luminance_min": _BRIGHT_LUMINANCE_MIN,
        "red_min": _RED_MIN,
        "red_dominance": _RED_DOMINANCE,
    }


def _scripted(job: _Job) -> None:
    try:
        dims = load_dimensions(
            job.settings.repo_root, job.asset.generation, subject_body(job.asset.subject)
        )
    except ValueError as error:
        raise _Failed(str(error)) from error
    plan = scripted_plan(dims, glb=job.prepared, out_dir=job.out)
    _blender(job, "split_scripted.py", "split-plan.json", plan, job.segmented)


# --- tripo ---


def _tripo(job: _Job) -> _Paid:
    """The paid result: this run's call, a resumed one, or a finished one recorded earlier."""
    call_id = job.plan.call_id
    if call_id is None:
        raise _Failed("plan.json: the tripo method needs call_id")
    record = _read_record(job)
    if record is not None and record.call_id == call_id and record.state == "done":
        return _recorded(job, record)
    resuming = record is not None and record.call_id == call_id
    pending = {"call_id": call_id, "state": "pending"}
    try:
        client = _fal_client(job.settings)
        completed = client.completed(call_id, job.raw)
    except (FalError, ValueError, OSError) as error:
        raise _Failed(str(error)) from error
    reduced = None if resuming or completed is not None else _reduce(job)
    try:
        if completed is not None:
            result = completed
        elif reduced is None:
            result = client.resume(call_id, job.raw)
        else:
            call = PlannedCall(
                call_id=call_id,
                generator="tripo-segment",
                images=(),
                slots=(),
                mesh=reduced,
                options={},
            )
            result = client.run(call, job.raw)
    except FalError as error:
        if error.resumable:
            _remember(job, pending)
            raise _Failed(
                f"{error}. The call is recorded as pending in {job.call_json}: re-run this stage "
                f"with the same plan.json and it resumes {call_id} without paying again"
            ) from error
        if resuming:  # the client refused to resume: say which record that was
            raise _Failed(
                f"{error}. The pending record is {job.call_json}: delete it only if the earlier "
                "run was stopped before it reached the spend guard (nothing was submitted)"
            ) from error
        raise _Failed(str(error)) from error
    except (SpendDenied, ValueError, OSError) as error:  # refused before or by the guard
        raise _Failed(str(error)) from error
    except BaseException:
        # An interrupt can land while a submitted call is still on fal's queue. The next `run`
        # would be denied by the guard, whose advice is a new tag, so leave the record that
        # makes the next run resume.
        with contextlib.suppress(_Failed):
            _remember(job, pending)
        raise
    paid = _Paid(result.files, format(result.cost, "f"))
    _remember(
        job,
        {
            "call_id": call_id,
            "state": "done",
            "request_id": result.request_id,
            "cost_usd": paid.cost_usd,
            "files": {key: path.name for key, path in result.files.items()},
        },
    )
    return paid


def _reduce(job: _Job) -> Path:
    reduced = job.out / "reduced.glb"
    plan: dict[str, object] = {
        "glb": str(job.prepared),
        "out_glb": str(reduced),
        "target_triangles": job.plan.reduce_to_triangles,
    }
    _blender(job, "reduce_mesh.py", "reduce-plan.json", plan, reduced)
    return reduced


def _read_record(job: _Job) -> _Record | None:
    path = job.call_json
    if not path.exists():
        return None
    where = f"{path} records a paid call, so it is never guessed at: fix or remove it by hand"
    try:
        data: object = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise _Failed(f"call.json could not be read ({error}); {where}") from error
    fields = cast("dict[str, object]", data) if isinstance(data, dict) else {}
    call_id, state = fields.get("call_id"), fields.get("state")
    if not isinstance(call_id, str) or state not in ("pending", "done"):
        raise _Failed(f"call.json has no call_id and a state of 'pending' or 'done'; {where}")
    files: dict[str, str] = {}
    raw_files = fields.get("files", {})
    if isinstance(raw_files, dict):
        for key, name in cast("dict[object, object]", raw_files).items():
            if not isinstance(name, str) or not name or Path(name).name != name:
                raise _Failed(f"call.json lists {key!r} as {name!r}, not a file name; {where}")
            files[str(key)] = name
    cost = fields.get("cost_usd")
    return _Record(
        call_id,
        "done" if state == "done" else "pending",
        files,
        cost if isinstance(cost, str) else "unknown",
    )


def _recorded(job: _Job, record: _Record) -> _Paid:
    files = {key: job.raw / name for key, name in record.files.items()}
    gone = [str(path) for path in files.values() if not path.is_file()]
    if gone:
        raise _Failed(
            f"call.json says {record.call_id} finished, but {', '.join(gone)} is missing. The "
            "call was paid for: restore the files, or add a ledger row and a new call_id to "
            "plan.json to pay for a new call"
        )
    return _Paid(files, record.cost_usd)


def _remember(job: _Job, record: Mapping[str, object]) -> None:
    _write(job.call_json, json.dumps(record, indent=2) + "\n", job)


def _place_tripo_result(job: _Job, paid: _Paid) -> None:
    """Put the result's GLB at `segmented.glb`, converting an FBX first. An unsupported result
    leaves a record and its paid files."""
    picked = _pick(paid.files)
    if picked is None:
        files = {key: path.relative_to(job.out).as_posix() for key, path in paid.files.items()}
        _write(
            job.parts_json,
            _dump(
                {
                    "outcome": "unsupported-result",
                    "candidate": job.plan.candidate,
                    "method": job.plan.method,
                    "call_id": job.plan.call_id,
                    "cost_usd": paid.cost_usd,
                    "files": files,
                }
            ),
            job,
        )
        raise _Failed(
            f"{job.plan.call_id}: the result has neither a GLB nor an FBX (files: "
            f"{', '.join(files) or 'none'}); the unsupported result is recorded in "
            f"{job.parts_json} and the paid files stay in {job.raw}",
            [job.parts_json],
        )
    source, kind = picked
    if kind == "glb":
        try:
            require_write_target_outside_repo(dest=job.segmented, repo_root=job.settings.repo_root)
            shutil.copyfile(source, job.segmented)
        except (ValueError, OSError) as error:
            raise _Failed(f"could not copy {source} to {job.segmented}: {error}") from error
        return
    plan: dict[str, object] = {"input": str(source), "out_glb": str(job.segmented)}
    _blender(job, "convert_to_glb.py", "convert-plan.json", plan, job.segmented)


def _sniff(path: Path) -> Literal["glb", "fbx"] | None:
    """What a result file is, from its first bytes: fal's URL extension is not trusted."""
    try:
        with path.open("rb") as handle:
            head = handle.read(32)
    except OSError:
        return None
    if head.startswith(b"glTF"):
        return "glb"
    if head.startswith((b"Kaydara FBX Binary", b"; FBX")):
        return "fbx"
    return None


def _pick(files: Mapping[str, Path]) -> tuple[Path, Literal["glb", "fbx"]] | None:
    """`model_urls.glb`, else `model_mesh` when it is a GLB, else an FBX to convert."""
    for key in ("model_urls.glb", "model_mesh"):
        path = files.get(key)
        if path is not None and _sniff(path) == "glb":
            return path, "glb"
    for key in ("model_urls.fbx", "model_mesh"):
        path = files.get(key)
        if path is not None and _sniff(path) == "fbx":
            return path, "fbx"
    return None


# --- shared steps ---


def _write(dest: Path, text: str, job: _Job) -> None:
    try:
        require_write_target_outside_repo(dest=dest, repo_root=job.settings.repo_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dest.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(text)
                handle.close()
                temporary.replace(dest)
            finally:
                temporary.unlink(missing_ok=True)
    except (ValueError, OSError) as error:
        raise _Failed(f"could not write {dest}: {error}") from error


def _dump(document: Mapping[str, object]) -> str:
    return json.dumps(document, indent=2) + "\n"


def _blender(
    job: _Job, script: str, plan_name: str, plan: Mapping[str, object], made: Path
) -> None:
    """Write `plan` next to the outputs and run `script` on it. `made` must exist afterwards."""
    plan_file = job.out / plan_name
    _write(plan_file, _dump(plan), job)
    try:
        made.unlink(missing_ok=True)  # a leftover must not pass for this run's output
        done = run_blender(
            job.settings.repo_root / "pipeline" / "blender" / script, ["--plan", str(plan_file)]
        )
    except FileNotFoundError as error:
        made.unlink(missing_ok=True)
        raise _Failed(str(error)) from error
    except subprocess.TimeoutExpired:
        made.unlink(missing_ok=True)
        raise _Failed(f"{script} timed out") from None
    except OSError as error:
        made.unlink(missing_ok=True)
        raise _Failed(f"could not run Blender for {script}: {error}") from error
    except BaseException:
        made.unlink(missing_ok=True)
        raise
    if done.returncode != 0:
        made.unlink(missing_ok=True)
        detail = (done.stderr.strip() or done.stdout.strip() or "no output")[-_STDERR_TAIL:]
        raise _Failed(f"{script} exited {done.returncode}: {detail}")
    if not made.is_file() or made.stat().st_size == 0:
        made.unlink(missing_ok=True)
        raise _Failed(f"{script} exited 0 but did not write {made}")


def _write_parts(job: _Job, paid: _Paid | None) -> list[str]:
    """Read `segmented.glb` and write `parts.json`. Returns the stage's messages."""
    try:
        total = mesh_stats(job.segmented)
        parts = part_stats(job.segmented)
    except (GlbError, OSError) as error:
        job.segmented.unlink(missing_ok=True)  # `cleanup` must not take a broken file for a split
        raise _Failed(f"{job.segmented} could not be read as a split mesh: {error}") from error
    names = {part.name for part in parts}
    found = [name for name in CONTRACT_PARTS if name in names]
    missing = [name for name in CONTRACT_PARTS if name not in names]
    document: dict[str, object] = {
        "outcome": "ok",
        "candidate": job.plan.candidate,
        "method": job.plan.method,
        "segmented": job.segmented.name,
        "triangles": total.triangles,
        "bbox_min": list(total.bbox_min),
        "bbox_max": list(total.bbox_max),
        "parts": [
            {
                "name": part.name,
                "triangles": part.triangles,
                "bbox_min": list(part.bbox_min),
                "bbox_max": list(part.bbox_max),
            }
            for part in parts
        ],
        "contract_parts_found": found,
        "contract_parts_missing": missing,
    }
    if paid is not None:
        document["call_id"] = job.plan.call_id
        document["cost_usd"] = paid.cost_usd
    _write(job.parts_json, _dump(document), job)
    summary = (
        f"{job.plan.method}: {len(parts)} parts, {total.triangles} triangles in {job.segmented}"
    )
    if missing:
        return [summary, f"missing contract parts: {', '.join(missing)}"]
    return [summary, f"all {len(CONTRACT_PARTS)} contract parts present"]

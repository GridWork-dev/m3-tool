"""Recovery never loses failure evidence or repeats an ambiguous paid submission."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_synth_stage import Setup, run, stage
from test_synth_stage import setup as setup

from m3_pipeline.config import Settings
from m3_pipeline.stages.lib.codex import CodexError
from m3_pipeline.stages.lib.critic import Issue, Verdict
from m3_pipeline.stages.lib.fal import CallResult, FalClient, FalError, PlannedCall
from m3_pipeline.stages.lib.provenance import load_provenance, write_provenance


def _constant[T](value: T) -> Callable[..., T]:
    def fake(*args: object, **kwargs: object) -> T:
        return value

    return fake


class FakeFal(FalClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, {})
        self.submits = 0
        self.resumes = 0
        self.complete = False
        self.fail = False

    def preflight(self, call: PlannedCall, out_dir: Path) -> None:
        pass

    def _result(self, call_id: str, out_dir: Path) -> CallResult:
        return CallResult(call_id, "request", {"image": out_dir / "result.png"}, Decimal("0.1"))

    def run(self, call: PlannedCall, out_dir: Path) -> CallResult:
        self.submits += 1
        if self.fail:
            raise FalError("ambiguous submit; inspect journal")
        (out_dir / "result.png").write_bytes(b"downloaded image")
        self.complete = True
        return self._result(call.call_id, out_dir)

    def completed(self, call_id: str, out_dir: Path) -> CallResult | None:
        return self._result(call_id, out_dir) if self.complete else None

    def resume(self, call_id: str, out_dir: Path) -> CallResult:
        self.resumes += 1
        raise FalError("cannot resume ambiguous submission without request id")


def test_failed_synthesis_preserves_image_provenance_approval_and_report(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(setup).ok
    root = setup[0]
    (root / "approved.json").write_text('{"views":{"side":"approved"}}')
    (root / "proportion.json").write_text('{"ok":false}')
    names = ["views/side.png", "provenance.json", "approved.json", "proportion.json"]
    before = {name: (root / name).read_bytes() for name in names}
    setup[1]["force"] = ["side"]

    def fails(*args: object, **kwargs: object) -> str:
        raise CodexError("process crashed")

    monkeypatch.setattr(stage, "run_codex", fails)
    assert not run(setup).ok
    assert before == {name: (root / name).read_bytes() for name in names}


@pytest.mark.parametrize(
    "text", ["codex critic failed: process crashed", "critic returned no valid verdict: prose"]
)
def test_infrastructure_verdict_is_unknown_and_cannot_enable_paid_fallback(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setattr(
        stage, "run_critic", _constant(Verdict(False, (Issue("blocker", text, ""),), ""))
    )
    assert not run(setup).ok
    assert load_provenance(setup[0] / "provenance.json")[0].critic_ok is None
    setup[1]["views"]["side"]["engine"] = "fal"
    setup[1]["fallback"] = ["side"]
    result = run(setup)
    assert not result.ok and "failed critic or proportion guard" in result.messages[-1]


def test_successful_fal_view_is_skipped_with_same_plan(setup: Setup) -> None:
    assert run(setup).ok
    path = setup[0] / "provenance.json"
    items = load_provenance(path)
    write_provenance(path, [replace(items[0], engine="fal")])
    setup[1]["views"]["side"]["engine"] = "fal"
    setup[1]["fallback"] = ["side"]
    assert run(setup).ok
    assert len(setup[2]) == 1


def _call_and_client(tmp_path: Path) -> tuple[PlannedCall, FakeFal, Path, Settings]:
    settings = Settings(tmp_path / "repo", tmp_path / "work")
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    return (
        PlannedCall("edit-side", "image-edit", (image,), ("front",), None, {"prompt": "car"}),
        FakeFal(settings),
        tmp_path / "work/fal/edit-side",
        settings,
    )


def test_paid_completed_call_is_recovered_without_submission(tmp_path: Path) -> None:
    call, client, out_dir, settings = _call_and_client(tmp_path)
    first = stage._paid_result(client, call, out_dir, settings)
    second = stage._paid_result(client, call, out_dir, settings)
    assert first == second
    assert client.submits == 1 and client.resumes == 0
    assert (out_dir / "intent.json").exists()
    assert second.files["image"].read_bytes() == b"downloaded image"


def test_ambiguous_paid_failure_is_resumed_never_resubmitted(tmp_path: Path) -> None:
    call, client, out_dir, settings = _call_and_client(tmp_path)
    client.fail = True
    with pytest.raises(FalError, match="ambiguous submit"):
        stage._paid_result(client, call, out_dir, settings)
    with pytest.raises(FalError, match="cannot resume"):
        stage._paid_result(client, call, out_dir, settings)
    assert client.submits == 1 and client.resumes == 1


def test_paid_call_id_cannot_be_reused_for_different_inputs(tmp_path: Path) -> None:
    call, client, out_dir, settings = _call_and_client(tmp_path)
    stage._paid_result(client, call, out_dir, settings)
    call.images[0].write_bytes(b"changed")
    with pytest.raises(ValueError, match="different inputs/options"):
        stage._paid_result(client, call, out_dir, settings)
    assert client.submits == 1


def test_nearest_mirrored_reference_uses_destination_view_slot(setup: Setup) -> None:
    # ViewRef.view already names the intended slot after preparation has mirrored it.
    from typing import cast

    from m3_pipeline.stages.lib.viewset_io import SpikeViewSet

    refs = cast(SpikeViewSet, stage.load_viewset(setup[4].work_dir, "e46-coupe")).entries()
    mirrored_side = replace(refs[0], image_id="mirrored", view="side_left", mirrored=True)
    front = replace(refs[0], image_id="front", view="front")
    rear = replace(refs[1], image_id="rear", view="rear")
    ranked = stage._nearest("side", [front, rear, mirrored_side])
    assert ranked[0].image_id == "mirrored"


def test_critic_checklist_names_requested_view(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[str] = []

    def critic(
        kind: str, checklist: Sequence[str], images: Sequence[Path], *, cwd: Path
    ) -> Verdict:
        received.extend(checklist)
        return Verdict(True, (), "ok")

    monkeypatch.setattr(stage, "run_critic", critic)
    assert run(setup).ok
    assert any("requested side view" in item for item in received)


def test_denied_authorization_can_be_corrected_without_an_ambiguous_intent(tmp_path: Path) -> None:
    from m3_pipeline.stages.lib.spend import SpendDenied

    call, _, out_dir, settings = _call_and_client(tmp_path)

    class DeniedFal(FakeFal):
        denied: bool = True

        def run(self, call: PlannedCall, out_dir: Path) -> CallResult:
            if self.denied:
                raise SpendDenied("session cap missing")
            return super().run(call, out_dir)

    client = DeniedFal(settings)
    with pytest.raises(SpendDenied):
        stage._paid_result(client, call, out_dir, settings)
    assert not (out_dir / "intent.json").exists()
    client.denied = False
    stage._paid_result(client, call, out_dir, settings)
    assert client.submits == 1


@pytest.mark.parametrize("refusal", ["missing-key", "invalid-option"])
def test_local_fal_refusals_leave_no_intent_and_corrected_calls_submit_once(
    tmp_path: Path, refusal: str
) -> None:
    from m3_pipeline.stages.lib.generators import PriceUnknown, load_generators

    call, _, out_dir, settings = _call_and_client(tmp_path)
    call.images[0].write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    call = replace(call, generator="trellis-2", slots=("front_34",), options={})
    registry = load_generators(Path(__file__).resolve().parents[1] / "generators.toml")
    environment = {} if refusal == "missing-key" else {"M3_FAL_KEY": "test-key-123"}

    class RealPreflightFal(FakeFal):
        def preflight(self, call: PlannedCall, out_dir: Path) -> None:
            FalClient.preflight(self, call, out_dir)

    client = RealPreflightFal(settings)
    FalClient.__init__(client, settings, registry, env=environment)
    invalid = (
        replace(call, options={"unsupported-option": True}) if refusal == "invalid-option" else call
    )
    with pytest.raises((FalError, PriceUnknown)):
        stage._paid_result(client, invalid, out_dir, settings)
    assert not (out_dir / "intent.json").exists()
    assert client.submits == 0
    environment["M3_FAL_KEY"] = "test-key-123"
    stage._paid_result(client, call, out_dir, settings)
    stage._paid_result(client, call, out_dir, settings)
    assert client.submits == 1

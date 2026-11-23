import pytest

from m3_pipeline.stages import REGISTRY, StageResult, register


def _stage(*_args: object) -> StageResult:
    return StageResult(True, [], [])


def test_register_adds_the_stage() -> None:
    try:
        assert register("fresh-stage")(_stage) is _stage
        assert REGISTRY["fresh-stage"] is _stage
    finally:
        REGISTRY.pop("fresh-stage", None)


def test_register_rejects_a_duplicate_name() -> None:
    try:
        register("twice")(_stage)
        with pytest.raises(ValueError, match="twice"):
            register("twice")(lambda asset, settings: StageResult(False, [], []))
        assert REGISTRY["twice"] is _stage  # the first stays
    finally:
        REGISTRY.pop("twice", None)


def test_register_rejects_a_stage_that_is_already_built_in() -> None:
    with pytest.raises(ValueError, match="validate"):
        register("validate")(_stage)

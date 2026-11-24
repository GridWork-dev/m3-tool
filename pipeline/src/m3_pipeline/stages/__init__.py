from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings


@dataclass
class StageResult:
    ok: bool
    messages: list[str]
    outputs: list[Path]


Stage = Callable[[AssetSpec, Settings], StageResult]

REGISTRY: dict[str, Stage] = {}


class UnknownStageError(KeyError):
    pass


def register(name: str) -> Callable[[Stage], Stage]:
    """Register `stage` under `name`. A second stage with the same name is an error."""

    def decorator(stage: Stage) -> Stage:
        if name in REGISTRY:
            raise ValueError(f"stage {name!r} is already registered")
        REGISTRY[name] = stage
        return stage

    return decorator


def run_stage(name: str, asset: AssetSpec, settings: Settings) -> StageResult:
    try:
        stage = REGISTRY[name]
    except KeyError:
        raise UnknownStageError(name) from None
    return stage(asset, settings)


# A stage registers itself when its module is imported, so every stage module is imported here.
# These imports stay at the bottom: the modules import StageResult and register from this package,
# which must be fully defined by then.
from m3_pipeline.stages import export as export  # noqa: E402
from m3_pipeline.stages import refs as refs  # noqa: E402
from m3_pipeline.stages import segment as segment  # noqa: E402
from m3_pipeline.stages import validate as validate  # noqa: E402

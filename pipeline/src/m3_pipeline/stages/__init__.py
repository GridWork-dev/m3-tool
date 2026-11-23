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
    def decorator(stage: Stage) -> Stage:
        REGISTRY[name] = stage
        return stage

    return decorator


def run_stage(name: str, asset: AssetSpec, settings: Settings) -> StageResult:
    try:
        stage = REGISTRY[name]
    except KeyError:
        raise UnknownStageError(name) from None
    return stage(asset, settings)

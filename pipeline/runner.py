"""Runs a contiguous range of stages, in order."""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

from pipeline.config import STAGES, BuildContext
from pipeline.db import drop_temp_tables

log = logging.getLogger("pipeline")


def load_stage(name: str) -> ModuleType:
    return importlib.import_module(f"pipeline.stages.{name}")


def stage_range(start: str = STAGES[0], stop: str = STAGES[-1]) -> tuple[str, ...]:
    if start not in STAGES or stop not in STAGES:
        raise ValueError(f"stages are {', '.join(STAGES)}")
    first, last = STAGES.index(start), STAGES.index(stop)
    if first > last:
        raise ValueError(f"--from {start} comes after --to {stop}")
    return STAGES[first : last + 1]


def run(ctx: BuildContext, start: str = STAGES[0], stop: str = STAGES[-1]) -> None:
    for name in stage_range(start, stop):
        drop_temp_tables(ctx.con)
        log.info("stage %s: start", name)
        load_stage(name).run(ctx)
        log.info("stage %s: done", name)

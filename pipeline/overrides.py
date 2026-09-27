"""Manual corrections (spec §5.4): ``pipeline/overrides/*.yaml``, always win.

Identity overrides (``merge_works``, ``split_work``) apply after duplicate
detection; series overrides apply after the ladder. An entry that references
something the build does not hold fails the run — a stale override is a bug
to fix, not something to skip.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from contextlib import contextmanager
from typing import Callable, Mapping, Union

import yaml

from pipeline._backend import series_key
from pipeline.group.decide import Decision
from pipeline.group.types import OVERRIDE_RUNG, Membership


class OverrideError(ValueError):
    pass


@dataclass(frozen=True)
class MergeWorks:
    survivor: str
    losers: tuple[str, ...]
    where: str = field(default="", compare=False)  # "file.yaml[3]", for errors


@dataclass(frozen=True)
class SplitWork:
    work: str
    editions: tuple[str, ...]
    where: str = field(default="", compare=False)  # "file.yaml[3]", for errors

    @property
    def new_work(self) -> str:
        """The split-off work's id: not a real OL id, but stable and unique."""
        return f"{self.work}~{min(self.editions)}"


@dataclass(frozen=True)
class SetSeries:
    work: str
    series: str
    position: float | None = None
    name: str | None = None
    where: str = field(default="", compare=False)  # "file.yaml[3]", for errors


@dataclass(frozen=True)
class RemoveFromSeries:
    work: str
    series: str
    where: str = field(default="", compare=False)  # "file.yaml[3]", for errors


@dataclass(frozen=True)
class RejectSeries:
    series: str
    where: str = field(default="", compare=False)  # "file.yaml[3]", for errors


@dataclass(frozen=True)
class RenameSeries:
    series: str
    name: str
    where: str = field(default="", compare=False)  # "file.yaml[3]", for errors


Override = Union[MergeWorks, SplitWork, SetSeries, RemoveFromSeries, RejectSeries, RenameSeries]


def normalize_series_key(raw: str) -> str:
    prefix, sep, rest = str(raw).partition(":")
    rest = rest.strip()
    if not sep or prefix not in ("wd", "ol") or not rest:
        raise OverrideError(f"series must be 'wd:Q…' or 'ol:<name>', got {raw!r}")
    return f"wd:{rest}" if prefix == "wd" else f"ol:{series_key(rest)}"


def _position(raw) -> float | None:
    return None if raw is None else float(raw)


def _merge_works(body) -> MergeWorks:
    if not isinstance(body, list) or len(body) < 2:
        raise OverrideError("needs a list of at least two work ids")
    return MergeWorks(body[0], tuple(body[1:]))


def _split_work(body) -> SplitWork:
    if not body.get("editions"):
        raise OverrideError("needs at least one edition")
    return SplitWork(body["work"], tuple(body["editions"]))


_PARSERS: dict[str, Callable[[object], Override]] = {
    "merge_works": _merge_works,
    "split_work": _split_work,
    "set_series": lambda b: SetSeries(b["work"], normalize_series_key(b["series"]),
                                      _position(b.get("position")), b.get("name")),
    "remove_from_series": lambda b: RemoveFromSeries(b["work"], normalize_series_key(b["series"])),
    "reject_series": lambda b: RejectSeries(normalize_series_key(b)),
    "rename_series": lambda b: RenameSeries(normalize_series_key(b["series"]), str(b["name"])),
}


def load_overrides(directory: Path) -> list[Override]:
    found: list[Override] = []
    for path in sorted(directory.glob("*.yaml")):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(entries, list):
            raise OverrideError(f"{path.name}: expected a list of entries")
        for index, entry in enumerate(entries):
            where = f"{path.name}[{index}]"
            if not isinstance(entry, dict) or len(entry) != 1:
                raise OverrideError(f"{where}: each entry is a single-key mapping")
            ((kind, body),) = entry.items()
            if kind not in _PARSERS:
                raise OverrideError(f"{where}: unknown override {kind!r}")
            try:
                found.append(replace(_PARSERS[kind](body), where=where))
            except OverrideError as exc:
                raise OverrideError(f"{where}: {kind}: {exc}") from None
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise OverrideError(f"{where}: {kind}: malformed ({exc!r})") from None
    return found


def _follow(aliases: Mapping[str, str], ol_id: str) -> str:
    seen = {ol_id}
    while ol_id in aliases and aliases[ol_id] not in seen:
        ol_id = aliases[ol_id]
        seen.add(ol_id)
    return ol_id


@dataclass
class IdentityPlan:
    aliases: dict[str, str]  # loser -> final survivor
    splits: list[SplitWork]
    edition_work: dict[str, str]  # edition -> final work


def apply_identity(overrides: list[Override], works: set[str], edition_work: Mapping[str, str],
                   aliases: Mapping[str, str]) -> IdentityPlan:
    """Fold ``merge_works`` and ``split_work`` into the duplicate-detection result."""
    merged = dict(aliases)
    splits: list[SplitWork] = []
    for op in overrides:
        with _located(op):
            _apply_identity_op(op, works, merged, splits)
    final = {loser: _follow(merged, loser) for loser in merged}
    moved = {e: final.get(w, w) for e, w in edition_work.items()}
    for op in splits:
        with _located(op):
            owner = final.get(op.work, op.work)
            for edition in op.editions:
                if moved.get(edition) != owner:
                    raise OverrideError(f"split_work: edition {edition} is not an edition of {op.work}")
                moved[edition] = op.new_work
    return IdentityPlan(final, splits, moved)


def _apply_identity_op(op: Override, works: set[str], merged: dict[str, str], splits: list[SplitWork]) -> None:
    if isinstance(op, MergeWorks):
        for ol_id in (op.survivor, *op.losers):
            if ol_id not in works:
                raise OverrideError(f"merge_works: unknown work {ol_id}")
        survivor = _follow(merged, op.survivor)
        for loser in op.losers:
            loser = _follow(merged, loser)
            if loser != survivor:
                merged[loser] = survivor
    elif isinstance(op, SplitWork):
        if op.work not in works:
            raise OverrideError(f"split_work: unknown work {op.work}")
        splits.append(op)


@contextmanager
def _located(op: Override):
    """Prefix an error raised while applying ``op`` with its file and index."""
    try:
        yield
    except OverrideError as exc:
        if op.where:
            raise OverrideError(f"{op.where}: {exc}") from None
        raise


def series_rejects(overrides: list[Override]) -> set[str]:
    return {op.series for op in overrides if isinstance(op, RejectSeries)}


def apply_series(overrides: list[Override], decision: Decision, works: set[str],
                 resolve: Callable[[str], str] = lambda w: w) -> None:
    """Apply set/remove/rename (rejects were fed to ``decide``), validating each."""
    for op in overrides:
        with _located(op):
            _apply_series_op(op, decision, works, resolve)


def _check_target(kind: str, series: str, decision: Decision) -> None:
    if series in decision.folded:
        raise OverrideError(f"{kind}: {series} was folded into {decision.folded[series]}; target that instead")
    if series not in decision.known_series:
        raise OverrideError(f"{kind}: no series {series} in this build")


def _apply_series_op(op: Override, decision: Decision, works: set[str], resolve: Callable[[str], str]) -> None:
    if isinstance(op, RejectSeries):
        _check_target("reject_series", op.series, decision)
    elif isinstance(op, SetSeries):
        work = resolve(op.work)
        if work not in works:
            raise OverrideError(f"set_series: unknown work {op.work}")
        if op.series in decision.folded:
            _check_target("set_series", op.series, decision)
        if op.series not in decision.known_series:
            if not (op.series.startswith("ol:") and op.name):
                raise OverrideError(f"set_series: no series {op.series}; give a name to create an ol: series")
            decision.known_series.add(op.series)
            decision.names[op.series] = op.name
        decision.memberships.setdefault(work, {})[op.series] = Membership(op.series, op.position, OVERRIDE_RUNG)
        decision.decided_by[work] = OVERRIDE_RUNG
    elif isinstance(op, RemoveFromSeries):
        work = resolve(op.work)
        if work not in works:
            raise OverrideError(f"remove_from_series: unknown work {op.work}")
        _check_target("remove_from_series", op.series, decision)
        ms = decision.memberships.get(work, {})
        if op.series not in ms:
            raise OverrideError(f"remove_from_series: {op.work} is not a member of {op.series}")
        del ms[op.series]
        if not ms:
            decision.decided_by[work] = None
    elif isinstance(op, RenameSeries):
        _check_target("rename_series", op.series, decision)
        decision.names[op.series] = op.name

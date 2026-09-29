# Overrides

Manual corrections, applied on every build and always winning (spec §5.4).
Each `*.yaml` file here is a list; files are read in name order. Series keys
are `wd:Q…` or `ol:<name>` (the name is normalized, so casing and punctuation
do not matter).

```yaml
- merge_works: [OL123W, OL456W]              # the rest merge into the first
- split_work: {work: OL789W, editions: [OL1M, OL2M]}   # new work id: OL789W~OL1M
- set_series: {work: OL27448W, series: "wd:Q45875", position: 3}
- set_series: {work: OL1W, series: "ol:lord of the rings", position: 1, name: "The Lord of the Rings"}
- remove_from_series: {work: OL27448W, series: "ol:dune"}
- reject_series: "ol:penguin classics"
- rename_series: {series: "wd:Q45875", name: "A Song of Ice and Fire"}
```

An entry that names a work or series the build does not hold fails the run:
a stale override is a bug to fix, not something to skip. Say why in a comment
above each entry — the next reader cannot see the report you were looking at.

## `z-librarian.yaml`

Written by `python -m scripts.export_overrides` (from `backend/`) from fixes
librarians made in the app; never edit it by hand. Its name sorts it last, so
an in-app fix wins over a hand-written one. When a release no longer holds a
book it names, the build fails like any stale override: undo the fix in the
app and export again, or delete the entry.

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

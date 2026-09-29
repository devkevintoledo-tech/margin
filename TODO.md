# TODO

Follow-ups to the catalog pipeline
([`docs/superpowers/specs/2026-09-26-catalog-pipeline-design.md`](docs/superpowers/specs/2026-09-26-catalog-pipeline-design.md)).
Each needs its own spec once the pipeline has shipped a first release.

- [x] **Librarian tools** — in-app merge, split, move-to-series and reorder
      for trusted users. Fixes are persisted in the pipeline's overrides
      format (spec §5.4), so every future release keeps them instead of
      re-deriving the mistake. Shipped: [plan](docs/superpowers/plans/2026-09-28-librarian-tools.md).
- [ ] **Catalog refresh** — monthly re-runs against new Open Library dumps
      and Wikidata: how a release is cut, reviewed (report diff, golden set)
      and loaded, and how books published after the last dump enter the
      catalog between releases.

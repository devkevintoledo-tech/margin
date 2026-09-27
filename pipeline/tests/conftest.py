import duckdb
import pytest
import respx

from pipeline.config import PIPELINE_DIR, BuildContext
from pipeline.tests.fixtures import world


def make_ctx(tmp_path, *, version="2026.10.1", releases=None) -> BuildContext:
    golden = tmp_path / "golden.yaml"
    golden.write_text(world.GOLDEN, encoding="utf-8")
    overrides = tmp_path / "overrides"
    overrides.mkdir(exist_ok=True)
    return BuildContext(
        build_dir=tmp_path / "build", con=duckdb.connect(), ol_dumps=dict(world.DUMPS),
        sparql_url=world.SPARQL, rules_dir=PIPELINE_DIR / "rules", overrides_dir=overrides,
        golden_path=golden, releases_dir=releases or tmp_path / "releases", version=version,
        sleep=lambda s: None,
    )


@pytest.fixture
def world_ctx(tmp_path):
    """A build context whose sources are the fixture world."""
    with respx.mock(assert_all_called=False) as router:
        world.serve(router)
        yield make_ctx(tmp_path)

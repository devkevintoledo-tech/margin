import subprocess
import sys

from pipeline.config import REPO


def test_backend_rules_import_without_app_settings():
    code = (
        "import sys\n"
        "import pipeline._backend\n"
        "assert 'app.config' not in sys.modules, 'rules pulled in app settings'\n"
        "assert 'sqlalchemy' not in sys.modules\n"
    )
    env = {"PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_backend_rules_are_the_apps():
    from pipeline._backend import canonical_key, display_title

    assert display_title("The Hobbit (Deluxe Edition)") == "The Hobbit"
    assert canonical_key("Red Rising 01", "Pierce Brown") == "red rising\x1fpierce brown"


def test_librarian_series_ids_are_the_pipelines():
    """A series a librarian creates in the app must be the row the next release upserts."""
    import pipeline._backend  # noqa: F401  (puts backend/ on sys.path)
    from app.services.series_identity import CATALOG_NAMESPACE, new_series_key, release_series_id

    from pipeline.config import MARGIN_NS
    from pipeline.ids import row_id, series_identity
    from pipeline.overrides import normalize_series_key

    assert CATALOG_NAMESPACE == MARGIN_NS
    key = new_series_key("The Lord of the Rings")
    assert key == normalize_series_key("ol:The Lord of the Rings")
    assert str(release_series_id(key)) == row_id(series_identity(key))

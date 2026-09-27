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

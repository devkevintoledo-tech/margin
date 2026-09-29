"""The identity rules must import without the app: the catalog pipeline runs offline."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_identity_rules_import_without_settings_or_http():
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY")}
    code = (
        "import sys\n"
        "import app.services.work_identity, app.services.series_identity, app.services.text, app.services.genre_inference\n"
        "leaked = {'app.config', 'httpx', 'sqlalchemy'} & set(sys.modules)\n"
        "assert not leaked, leaked\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

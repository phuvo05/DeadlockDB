from pathlib import Path
import subprocess
import sys


def test_app_imports_with_frontend_directory_available() -> None:
    backend_directory = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print(app.title)"],
        cwd=backend_directory,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

import os
import sys
import tempfile

backend_dir = os.path.abspath("silarisV2-main/backend")
venv_site = os.path.abspath("silarisV2-main/.venv/Lib/site-packages")

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if venv_site not in sys.path:
    sys.path.insert(0, venv_site)

os.environ["PYTHONPATH"] = f"{backend_dir};{venv_site}"
os.environ["YOLO_CONFIG_DIR"] = tempfile.gettempdir()

import pytest

if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else ["silarisV2-main/backend/tests", "-v"]
    code = pytest.main(args)
    sys.exit(code)


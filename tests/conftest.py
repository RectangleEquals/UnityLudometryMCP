import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PROTOCOL = REPO / "protocol"

# The generators live outside the package; tests import them for freshness checks.
sys.path.insert(0, str(PROTOCOL / "codegen"))

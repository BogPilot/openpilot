"""cereal ships inside the openpilot package in this tree (openpilot/cereal); there is no top-level `cereal` module on the
device. A bare `from cereal import ...` raises ModuleNotFoundError there: in bogpilot_mapd's main() it killed the Map Data
downloader at every start (the manager never restarts it), and in a try block it silently turns a feature off."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[4]          # .../openpilot (the package holding cereal/)
BARE = re.compile(r"^\s*(from\s+cereal(\.|\s)|import\s+cereal(\.|\s|$))", re.M)


def test_cereal_lives_in_the_openpilot_package():
  assert (PKG / "cereal" / "__init__.py").is_file()


def test_no_bare_cereal_imports():
  bad = []
  for f in PKG.rglob("*.py"):
    if "__pycache__" in f.parts:
      continue
    text = f.read_text(errors="replace")
    for m in BARE.finditer(text):
      line = text.count("\n", 0, m.start()) + 1
      bad.append(f"{f.relative_to(PKG)}:{line}")
  assert not bad, "use openpilot.cereal: " + ", ".join(bad)


def test_supervisor_main_imports_resolve():
  src = (PKG / "system" / "bogpilot" / "osm" / "supervisor.py").read_text()
  assert "from openpilot.cereal import messaging" in src
  assert (PKG / "cereal" / "messaging" / "__init__.py").is_file()

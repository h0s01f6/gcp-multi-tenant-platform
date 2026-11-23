"""The committed ABC/XYZ examples equal what the generators produce now."""
from tests.conftest import ROOT
from tools.iac.examples import build


def test_examples_are_current():
    for rel, text in build().items():
        assert (ROOT / "examples" / rel).read_text() == text, f"examples/{rel} is stale – run python3 -m tools.iac.examples"

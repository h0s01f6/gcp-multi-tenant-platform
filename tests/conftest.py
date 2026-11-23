import pathlib
import shutil
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def reg(tmp_path):
    """Copy of the example registry that a test can modify."""
    dst = tmp_path / "registry"
    shutil.copytree(ROOT / "registry", dst)

    class R:
        root = dst

        def read(self, rel):
            return yaml.safe_load((dst / rel).read_text())

        def write(self, rel, data):
            (dst / rel).write_text(yaml.safe_dump(data, sort_keys=False))

        def edit(self, rel, fn):
            data = self.read(rel)
            fn(data)
            self.write(rel, data)

        def raw(self, rel, text):
            (dst / rel).write_text(text)

    return R()


@pytest.fixture
def sec(tmp_path):
    """Copy of security/ that a test can modify (D6/D7/D9)."""
    dst = tmp_path / "security"
    shutil.copytree(ROOT / "security", dst)

    class S:
        root = dst

        def edit(self, rel, fn):
            data = yaml.safe_load((dst / rel).read_text())
            fn(data)
            (dst / rel).write_text(yaml.safe_dump(data, sort_keys=False))

    return S()

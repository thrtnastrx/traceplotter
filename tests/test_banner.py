from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from traceplotter.banner import DualBanner, ToolbarChip


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    return app


def test_dual_banner_persists_and_resets(tmp_path, qapp) -> None:
    del qapp
    chips = {
        "a": ToolbarChip("a", QPushButton("A")),
        "b": ToolbarChip("b", QLabel("B")),
        "c": ToolbarChip("c", QPushButton("C")),
    }
    path = tmp_path / "toolbar-layout.json"
    banner = DualBanner(chips, [["a", "b"], ["c"]], path=path)
    assert banner.current_layout() == [["a", "b"], ["c"]]
    assert chips["a"]._grip.isHidden()
    banner.set_layout_edit(True)
    assert not chips["a"]._grip.isHidden()
    banner.apply_layout([["c", "a"], ["b"]])
    banner.persist()
    chips2 = {
        "a": ToolbarChip("a", QPushButton("A")),
        "b": ToolbarChip("b", QLabel("B")),
        "c": ToolbarChip("c", QPushButton("C")),
    }
    reloaded = DualBanner(chips2, [["a", "b"], ["c"]], path=path)
    assert reloaded.current_layout() == [["c", "a"], ["b"]]
    reloaded.reset_layout()
    assert reloaded.current_layout() == [["a", "b"], ["c"]]

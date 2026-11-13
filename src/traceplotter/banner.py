"""Two-row draggable toolbar banner with persistent layout."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

MIME = "application/x-traceplotter-toolbar-item"
PANE_MIME = "application/x-traceplotter-pane"


def default_banner_path() -> Path:
    from .paths import default_app_support_dir

    return default_app_support_dir() / "toolbar-layout.json"


def default_panes_path() -> Path:
    from .paths import default_app_support_dir

    return default_app_support_dir() / "pane-layout.json"


class ToolbarChip(QFrame):
    """Draggable wrapper around a toolbar control."""

    def __init__(self, item_id: str, body: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item_id = item_id
        self._layout_edit = False
        self._drag_start: QPoint | None = None
        self.setObjectName("toolbarChip")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 6, 2)
        row.setSpacing(4)
        self._grip = QLabel("⋮⋮")
        self._grip.setObjectName("toolbarGrip")
        self._grip.setToolTip("Drag to rearrange")
        self._grip.setCursor(Qt.CursorShape.OpenHandCursor)
        self._grip.installEventFilter(self)
        row.addWidget(self._grip)
        row.addWidget(body)
        self.set_layout_edit(False)

    def set_layout_edit(self, enabled: bool) -> None:
        self._layout_edit = enabled
        self._grip.setVisible(enabled)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Keep chip chrome subtle when not editing.
        margins = (4, 2, 6, 2) if enabled else (0, 0, 0, 0)
        self.layout().setContentsMargins(*margins)
        if enabled:
            self.setObjectName("toolbarChip")
        else:
            self.setObjectName("toolbarChipFlat")
        self.style().unpolish(self)
        self.style().polish(self)

    def eventFilter(self, watched, event: QEvent) -> bool:  # noqa: N802
        if watched is self._grip and self._layout_edit:
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_start = event.position().toPoint()
                    self._grip.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return False
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_start = None
                self._grip.setCursor(Qt.CursorShape.OpenHandCursor)
                return False
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if (
                    self._drag_start is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                    and (event.position().toPoint() - self._drag_start).manhattanLength() >= 6
                ):
                    self._start_drag()
                    self._drag_start = None
                    return True
        return super().eventFilter(watched, event)

    def _start_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, QByteArray(self.item_id.encode("utf-8")))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(QPoint(12, self.height() // 2))
        self.hide()
        result = drag.exec(Qt.DropAction.MoveAction)
        if result != Qt.DropAction.MoveAction:
            self.show()


class BannerRow(QWidget):
    """One horizontal drop target row for toolbar chips."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bannerRow")
        self.setAcceptDrops(True)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self._layout_edit = False

    def set_layout_edit(self, enabled: bool) -> None:
        self._layout_edit = enabled
        self.setObjectName("bannerRowEdit" if enabled else "bannerRow")
        self.style().unpolish(self)
        self.style().polish(self)

    def item_ids(self) -> list[str]:
        return [chip.item_id for chip in self.chips()]

    def chips(self) -> list[ToolbarChip]:
        return [
            self._layout.itemAt(i).widget()
            for i in range(self._layout.count() - 1)
            if isinstance(self._layout.itemAt(i).widget(), ToolbarChip)
        ]

    def add_chip(self, chip: ToolbarChip, index: int | None = None) -> None:
        chip.setParent(self)
        chip.show()
        insert_at = self._layout.count() - 1 if index is None else max(0, min(index, self._layout.count() - 1))
        self._layout.insertWidget(insert_at, chip)
        self.changed.emit()

    def take_chip(self, item_id: str) -> ToolbarChip | None:
        for index in range(self._layout.count() - 1):
            widget = self._layout.itemAt(index).widget()
            if isinstance(widget, ToolbarChip) and widget.item_id == item_id:
                self._layout.removeWidget(widget)
                widget.setParent(None)
                self.changed.emit()
                return widget
        return None

    def clear_chips(self) -> list[ToolbarChip]:
        chips = self.chips()
        for chip in chips:
            self._layout.removeWidget(chip)
            chip.setParent(None)
        if chips:
            self.changed.emit()
        return chips

    def _insert_index_at(self, pos: QPoint) -> int:
        for index, chip in enumerate(self.chips()):
            if pos.x() < chip.geometry().center().x():
                return index
        return len(self.chips())

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._layout_edit and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._layout_edit and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not self._layout_edit or not event.mimeData().hasFormat(MIME):
            event.ignore()
            return
        item_id = bytes(event.mimeData().data(MIME)).decode("utf-8")
        banner = self.parent()
        while banner is not None and not isinstance(banner, DualBanner):
            banner = banner.parent()
        if not isinstance(banner, DualBanner):
            event.ignore()
            return
        chip = banner.take_chip(item_id)
        if chip is None:
            event.ignore()
            return
        self.add_chip(chip, self._insert_index_at(event.position().toPoint()))
        event.acceptProposedAction()
        banner.persist()


class DualBanner(QWidget):
    """Two-row rearrangeable toolbar banner."""

    layout_changed = Signal()

    def __init__(
        self,
        chips: dict[str, ToolbarChip],
        default_rows: list[list[str]],
        path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chips = chips
        self._default_rows = [list(row) for row in default_rows]
        self._path = path or default_banner_path()
        self._layout_edit = False
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self.row1 = BannerRow(self)
        self.row2 = BannerRow(self)
        root.addWidget(self.row1)
        root.addWidget(self.row2)
        self.row1.changed.connect(self.layout_changed.emit)
        self.row2.changed.connect(self.layout_changed.emit)
        self.apply_layout(self._load_layout() or self._default_rows)
        self.set_layout_edit(False)

    def set_layout_edit(self, enabled: bool) -> None:
        self._layout_edit = enabled
        self.row1.set_layout_edit(enabled)
        self.row2.set_layout_edit(enabled)
        for chip in self._chips.values():
            chip.set_layout_edit(enabled)

    def rows(self) -> tuple[BannerRow, BannerRow]:
        return self.row1, self.row2

    def take_chip(self, item_id: str) -> ToolbarChip | None:
        return self.row1.take_chip(item_id) or self.row2.take_chip(item_id)

    def current_layout(self) -> list[list[str]]:
        return [self.row1.item_ids(), self.row2.item_ids()]

    def apply_layout(self, rows: list[list[str]]) -> None:
        orphaned = self.row1.clear_chips() + self.row2.clear_chips()
        available = {chip.item_id: chip for chip in orphaned}
        available.update(self._chips)
        placed: set[str] = set()
        normalized = list(rows[:2]) + [[], []]
        for row_widget, item_ids in zip((self.row1, self.row2), normalized[:2], strict=True):
            for item_id in item_ids:
                chip = available.get(item_id)
                if chip is None or item_id in placed:
                    continue
                row_widget.add_chip(chip)
                placed.add(item_id)
        for item_id, chip in available.items():
            if item_id not in placed:
                self.row2.add_chip(chip)
        self.set_layout_edit(self._layout_edit)

    def reset_layout(self) -> None:
        self.apply_layout(self._default_rows)
        self.persist()

    def persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rows": self.current_layout()}
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.layout_changed.emit()

    def _load_layout(self) -> list[list[str]] | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            rows = data.get("rows")
            if not isinstance(rows, list) or len(rows) < 1:
                return None
            parsed: list[list[str]] = []
            for row in rows[:2]:
                if not isinstance(row, list):
                    return None
                parsed.append([str(item) for item in row])
            while len(parsed) < 2:
                parsed.append([])
            return parsed
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None


class PaneShell(QFrame):
    """Content pane with an optional drag handle for layout editing."""

    def __init__(self, pane_id: str, body: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pane_id = pane_id
        self._layout_edit = False
        self._drag_start: QPoint | None = None
        self._swap_callback = None
        self.setObjectName("paneShell")
        self.setAcceptDrops(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._header = QWidget()
        self._header.setObjectName("paneHeader")
        header_row = QHBoxLayout(self._header)
        header_row.setContentsMargins(4, 2, 4, 2)
        self._grip = QLabel("⋮⋮")
        self._grip.setObjectName("toolbarGrip")
        self._grip.setToolTip("Drag to swap panes")
        self._grip.setCursor(Qt.CursorShape.OpenHandCursor)
        self._grip.installEventFilter(self)
        header_row.addWidget(self._grip)
        header_row.addStretch(1)
        root.addWidget(self._header)
        root.addWidget(body, 1)
        self._body = body
        self.set_layout_edit(False)

    def set_swap_callback(self, callback) -> None:
        self._swap_callback = callback

    def set_layout_edit(self, enabled: bool) -> None:
        self._layout_edit = enabled
        self._header.setVisible(enabled)
        self.setAcceptDrops(enabled)

    def eventFilter(self, watched, event: QEvent) -> bool:  # noqa: N802
        if watched is self._grip and self._layout_edit:
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_start = event.position().toPoint()
                    self._grip.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return False
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_start = None
                self._grip.setCursor(Qt.CursorShape.OpenHandCursor)
                return False
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if (
                    self._drag_start is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                    and (event.position().toPoint() - self._drag_start).manhattanLength() >= 6
                ):
                    self._start_drag()
                    self._drag_start = None
                    return True
        return super().eventFilter(watched, event)

    def _start_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(PANE_MIME, QByteArray(self.pane_id.encode("utf-8")))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab().scaled(180, 100, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._layout_edit and event.mimeData().hasFormat(PANE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._layout_edit and event.mimeData().hasFormat(PANE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not self._layout_edit or not event.mimeData().hasFormat(PANE_MIME):
            event.ignore()
            return
        source_id = bytes(event.mimeData().data(PANE_MIME)).decode("utf-8")
        if source_id == self.pane_id:
            event.ignore()
            return
        if self._swap_callback:
            self._swap_callback(source_id, self.pane_id)
            event.acceptProposedAction()
        else:
            event.ignore()

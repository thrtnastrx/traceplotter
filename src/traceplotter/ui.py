"""PySide6 UI — PingPlotter-inspired layout with hop colors and focus graph."""

from __future__ import annotations

import ipaddress
import json
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCloseEvent,
    QCursor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .engine import (
    TIME_WINDOW_CHOICES,
    ContinuousTracer,
    HopStats,
    ProbeResult,
    SampleStore,
    SubnetSweeper,
    TimelinePoint,
    expand_ipv4_spec,
    latency_band,
    local_subnet_suggestion,
    resolve_ipv4,
    reverse_dns,
)
from .banner import DualBanner, PaneShell, ToolbarChip, default_panes_path
from .hostnames import HostnameBook
from .scans import ScanLibrary, probe_results_from_saved
from .theme import Preferences, THEMES, current_theme, set_theme
from .traces import TraceLibrary


def _labeled_control(label: str, widget: QWidget) -> QWidget:
    wrap = QWidget()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(QLabel(label))
    row.addWidget(widget)
    return wrap


def ipv4_sort_key(value: str) -> tuple[int, int | str]:
    """Numeric IPv4 order; non-IPv4 hostnames sort after addresses."""
    text = value.strip()
    try:
        return (0, int(ipaddress.IPv4Address(text)))
    except ValueError:
        return (1, text.lower())


def target_sort_key(target: str, hostname: str | None, mode: str) -> tuple:
    name = (hostname or "").strip().lower()
    ip_key = ipv4_sort_key(target)
    if mode == "hostname":
        # Named hosts first (A–Z), then unnamed by IP.
        return (0 if name else 1, name, ip_key)
    return ip_key


class CompactHostHeader(QHeaderView):
    """Short unlabeled header: sort arrow + resize only (no 1/2 column numbers)."""

    HEADER_HEIGHT = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("hostTargetsHeader")
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)
        self.setHighlightSections(False)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedHeight(self.HEADER_HEIGHT)
        self.setMinimumHeight(self.HEADER_HEIGHT)
        self.setMaximumHeight(self.HEADER_HEIGHT)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        hint.setHeight(self.HEADER_HEIGHT)
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setHeight(self.HEADER_HEIGHT)
        return hint

    def sectionSizeFromContents(self, logical_index: int) -> QSize:  # noqa: N802
        size = super().sectionSizeFromContents(logical_index)
        size.setHeight(self.HEADER_HEIGHT)
        return size

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # noqa: N802
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = rect
        option.section = logical_index
        option.text = ""
        option.textAlignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if self.isSortIndicatorShown() and self.sortIndicatorSection() == logical_index:
            if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
                option.sortIndicator = QStyleOptionHeader.SortIndicator.SortUp
            else:
                option.sortIndicator = QStyleOptionHeader.SortIndicator.SortDown
        else:
            option.sortIndicator = QStyleOptionHeader.SortIndicator.None_
        painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)
        painter.restore()


# Latency band colors (shared across themes)
GREEN = QColor("#7ac943")
YELLOW = QColor("#f5c542")
RED = QColor("#e85d5d")
OUTAGE_FOCUS = QColor("#e85d5d")


def _latency(value: float | None) -> str:
    return "" if value is None else f"{value:.1f}"


def _band_color(ms: float | None, soft: bool = False) -> QColor:
    theme = current_theme()
    band = latency_band(ms)
    if band == "green":
        return theme.green_soft if soft else GREEN
    if band == "yellow":
        return theme.yellow_soft if soft else YELLOW
    if band == "red":
        return theme.red_soft if soft else RED
    return QColor(theme.muted)


class HopBadgeItem(QTableWidgetItem):
    """Hop number cell; painted as a colored circle by HopCircleDelegate."""

    def __init__(self, hop: int, ms: float | None) -> None:
        super().__init__(str(hop))
        self.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setData(Qt.ItemDataRole.UserRole, ms)
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)


class HopCircleDelegate(QStyledItemDelegate):
    """PingPlotter-style filled hop circles."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        ms = index.data(Qt.ItemDataRole.UserRole)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = current_theme()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#3d6ea8") if theme.key == "dark" else QColor("#dce8f8"))
        else:
            painter.fillRect(option.rect, theme.panel)
        size = min(option.rect.width(), option.rect.height()) - 8
        size = max(18, size)
        circle = QRect(
            option.rect.center().x() - size // 2,
            option.rect.center().y() - size // 2,
            size,
            size,
        )
        painter.setBrush(_band_color(ms if isinstance(ms, (int, float)) else None))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(circle)
        painter.setPen(QColor("#ffffff"))
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(text))
        painter.restore()


class FocusChart(QWidget):
    """Latency bars painted at the same Y as each hop-table row."""

    def __init__(self, table: QTableWidget) -> None:
        super().__init__()
        self.setMinimumWidth(220)
        self._table = table
        self._hops: list[HopStats] = []
        table.verticalScrollBar().valueChanged.connect(self.update)
        table.horizontalHeader().geometriesChanged.connect(self.update)
        table.verticalHeader().sectionResized.connect(lambda *_: self.update())

    def set_hops(self, hops: list[HopStats]) -> None:
        self._hops = hops
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        theme = current_theme()
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.panel)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Keep bars aligned with hop-table rows (match header height; no title).
        header_h = self._table.horizontalHeader().height()
        body = self.rect().adjusted(8, header_h, -8, 0)
        if not self._hops:
            painter.setPen(QColor(theme.muted))
            painter.drawText(body, Qt.AlignmentFlag.AlignCenter, "No hop data")
            return

        max_ms = max(
            250.0,
            max((h.last_ms or h.avg_ms or 0.0) for h in self._hops) * 1.1,
        )
        for color, lo, hi in (
            (theme.green_soft, 0, 100),
            (theme.yellow_soft, 100, 200),
            (theme.red_soft, 200, max_ms),
        ):
            x0 = body.left() + body.width() * lo / max_ms
            x1 = body.left() + body.width() * min(hi, max_ms) / max_ms
            painter.fillRect(QRectF(x0, body.top(), x1 - x0, body.height()), color)

        painter.setPen(QPen(theme.grid_color, 1))
        painter.drawLine(0, header_h, self.width(), header_h)

        rows = min(len(self._hops), self._table.rowCount())
        for row in range(rows):
            hop = self._hops[row]
            y = header_h + self._table.rowViewportPosition(row)
            row_h = self._table.rowHeight(row)
            if y + row_h < header_h or y > self.height():
                continue
            bar_h = max(10.0, row_h - 8)
            top = y + (row_h - bar_h) / 2
            # Current timeout / no reply → full-width red bar (PingPlotter-style).
            if hop.last_ms is None and hop.sent > 0:
                painter.fillRect(QRectF(body.left(), top, body.width(), bar_h), OUTAGE_FOCUS)
                continue
            value = hop.last_ms if hop.last_ms is not None else hop.avg_ms
            if value is None:
                continue
            width = max(4.0, body.width() * value / max_ms)
            painter.fillRect(QRectF(body.left(), top, width, bar_h), _band_color(value))


def _naive_local(value: datetime) -> datetime:
    """Normalize timeline stamps so aware/naive values can be compared safely."""
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def clamp_timeline_view_end(
    view_end: datetime,
    *,
    now: datetime,
    window_seconds: float,
    earliest: datetime | None,
) -> datetime:
    """Keep the visible window ending at/before now and not before available history."""
    window = max(1.0, float(window_seconds))
    now_local = _naive_local(now)
    end = min(_naive_local(view_end), now_local)
    if earliest is None:
        return end
    min_end = _naive_local(earliest) + timedelta(seconds=window)
    if min_end >= now_local:
        return now_local
    return max(min_end, end)


class TimelineChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self._points: list[TimelinePoint] = []
        self._window_seconds = 15 * 60
        self._window_label = "15 min"
        self._follow_live = True
        self._view_end: datetime | None = None
        self._drag_origin: QPoint | None = None
        self._drag_origin_end: datetime | None = None

    def set_window(self, seconds: int, label: str) -> None:
        self._window_seconds = max(1, seconds)
        self._window_label = label
        if not self._follow_live and self._view_end is not None:
            self._view_end = self._clamped_end(self._view_end)
        self.update()

    def set_points(self, points: list[TimelinePoint]) -> None:
        self._points = [
            TimelinePoint(_naive_local(point.timestamp), point.latency_ms, point.loss_percent)
            for point in points
        ]
        if not self._follow_live and self._view_end is not None:
            self._view_end = self._clamped_end(self._view_end)
            if self._view_end >= datetime.now() - timedelta(milliseconds=50):
                self.reset_to_current()
                return
        self.update()

    def reset_to_current(self) -> None:
        self._follow_live = True
        self._view_end = None
        self._drag_origin = None
        self._drag_origin_end = None
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.update()

    def is_following_live(self) -> bool:
        return self._follow_live

    def _earliest(self) -> datetime | None:
        return self._points[0].timestamp if self._points else None

    def _clamped_end(self, view_end: datetime, now: datetime | None = None) -> datetime:
        return clamp_timeline_view_end(
            view_end,
            now=now or datetime.now(),
            window_seconds=self._window_seconds,
            earliest=self._earliest(),
        )

    def _view_range(self) -> tuple[datetime, datetime]:
        now = datetime.now()
        if self._follow_live or self._view_end is None:
            end = now
        else:
            end = self._clamped_end(self._view_end, now=now)
        start = end - timedelta(seconds=self._window_seconds)
        return start, end

    def _plot_area(self) -> QRectF:
        return QRectF(self.rect().adjusted(48, 18, -14, -28))

    def _x_for(self, timestamp: datetime, start: datetime, area: QRectF) -> float:
        elapsed = (timestamp - start).total_seconds()
        ratio = min(1.0, max(0.0, elapsed / self._window_seconds))
        return area.left() + area.width() * ratio

    def _can_pan(self) -> bool:
        earliest = self._earliest()
        if earliest is None:
            return False
        return (datetime.now() - earliest).total_seconds() > self._window_seconds

    def _context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        reset = QAction("Reset timeline to current", self)
        reset.setEnabled(not self._follow_live)
        reset.triggered.connect(self.reset_to_current)
        menu.addAction(reset)
        menu.exec(self.mapToGlobal(pos))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._can_pan():
            _start, end = self._view_range()
            self._drag_origin = event.position().toPoint()
            self._drag_origin_end = end if self._follow_live else self._clamped_end(end)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._drag_origin is not None
            and self._drag_origin_end is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            area = self._plot_area()
            width = max(1.0, area.width())
            dx = event.position().x() - self._drag_origin.x()
            if abs(dx) < 2:
                event.accept()
                return
            # Drag right → older history (content follows the hand).
            delta_seconds = -dx * (self._window_seconds / width)
            proposed = self._drag_origin_end + timedelta(seconds=delta_seconds)
            self._view_end = self._clamped_end(proposed)
            if self._view_end >= datetime.now() - timedelta(milliseconds=50):
                self.reset_to_current()
                # Keep drag origin so continuing the gesture can leave live again.
                self._drag_origin = event.position().toPoint()
                self._drag_origin_end = datetime.now()
            else:
                self._follow_live = False
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._drag_origin_end = None
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            if not self._follow_live and self._view_end is not None:
                if self._view_end >= datetime.now() - timedelta(milliseconds=50):
                    self.reset_to_current()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        theme = current_theme()
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.panel)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._plot_area()
        start, end = self._view_range()
        points = [
            point
            for point in self._points
            if start <= point.timestamp <= end + timedelta(seconds=0.5)
        ]
        max_ms = 250.0
        valid = [(p.timestamp, p.latency_ms) for p in points if p.latency_ms is not None]
        if valid:
            max_ms = max(250.0, max(value for _, value in valid) * 1.15)
        for color, lo, hi in (
            (theme.green_soft, 0, 100),
            (theme.yellow_soft, 100, 200),
            (theme.red_soft, 200, max_ms),
        ):
            y1 = area.bottom() - area.height() * min(hi, max_ms) / max_ms
            y0 = area.bottom() - area.height() * lo / max_ms
            painter.fillRect(QRectF(area.left(), y1, area.width(), y0 - y1), color)

        # Solid red outage columns for missed destination samples.
        min_bar = max(3.0, area.width() / max(120.0, self._window_seconds / 2.0))
        for index, point in enumerate(points):
            if point.latency_ms is not None and point.loss_percent < 100:
                continue
            left_ts = points[index - 1].timestamp if index else max(start, point.timestamp - timedelta(seconds=2))
            right_ts = (
                points[index + 1].timestamp
                if index + 1 < len(points)
                else min(end, point.timestamp + timedelta(seconds=2))
            )
            # Span from midpoint with previous to midpoint with next.
            span_left = left_ts + (point.timestamp - left_ts) / 2
            span_right = point.timestamp + (right_ts - point.timestamp) / 2
            x0 = self._x_for(span_left, start, area)
            x1 = self._x_for(span_right, start, area)
            painter.fillRect(
                QRectF(x0, area.top(), max(min_bar, x1 - x0), area.height()),
                theme.outage,
            )

        painter.setPen(QPen(theme.grid_color, 1))
        for division in range(5):
            y = area.top() + area.height() * division / 4
            painter.drawLine(int(area.left()), int(y), int(area.right()), int(y))
        # Time tick marks along the selected window.
        tick_count = 6
        painter.setPen(QColor(theme.muted))
        for tick in range(tick_count + 1):
            ratio = tick / tick_count
            x = area.left() + area.width() * ratio
            painter.drawLine(int(x), int(area.bottom()), int(x), int(area.bottom() + 4))
            stamp = start + timedelta(seconds=self._window_seconds * ratio)
            painter.drawText(
                QRectF(x - 28, area.bottom() + 4, 56, 16),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                stamp.strftime("%H:%M:%S"),
            )

        painter.setPen(theme.text_color)
        painter.drawText(4, int(area.top() + 8), f"{max_ms:.0f}")
        painter.drawText(8, int(area.bottom()), "0")
        mode = self._window_label if self._follow_live else f"{self._window_label} · historical"
        painter.drawText(
            int(area.left()),
            14,
            f"Time graph — endpoint latency (ms)  ·  {mode}",
        )
        if not points:
            painter.setPen(QColor(theme.muted))
            painter.drawText(area.toRect(), Qt.AlignmentFlag.AlignCenter, "Waiting for samples…")
            return
        if not valid:
            return

        painter.setPen(QPen(QColor("#2f6fed"), 2))
        previous: QPointF | None = None
        previous_ts: datetime | None = None
        gap_limit = max(self._window_seconds / 40.0, 8.0)
        for timestamp, value in valid:
            point = QPointF(
                self._x_for(timestamp, start, area),
                area.bottom() - area.height() * value / max_ms,
            )
            if previous is not None and previous_ts is not None:
                if (timestamp - previous_ts).total_seconds() <= gap_limit:
                    painter.drawLine(previous, point)
            previous = point
            previous_ts = timestamp


class ScanSignals(QObject):
    result = Signal(object)
    finished = Signal()


class RemoteSubnetScanDialog(QDialog):
    add_targets = Signal(list)

    def __init__(
        self,
        parent: QWidget | None = None,
        hostnames: HostnameBook | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Subnet scan")
        self.resize(820, 560)
        self._results: dict[str, ProbeResult] = {}
        self._dns: dict[str, str] = {}
        self._hostnames = hostnames or HostnameBook()
        self._library = ScanLibrary()
        self._loading_history = False
        self._stop = threading.Event()
        self._signals = ScanSignals()
        self._signals.result.connect(self._append_result)
        self._signals.finished.connect(self._scan_finished)

        self.spec = QLineEdit(local_subnet_suggestion())
        self.spec.setPlaceholderText("10.50.0.0/24 or 10.50.0.10-10.50.0.50")
        self.workers = QSpinBox()
        self.workers.setRange(1, 256)
        self.workers.setValue(64)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.1, 10.0)
        self.timeout.setSingleStep(0.1)
        self.timeout.setValue(0.8)
        self.timeout.setSuffix(" s")

        form = QFormLayout()
        form.addRow("IPv4 CIDR or range", self.spec)
        form.addRow("Concurrent probes", self.workers)
        form.addRow("Timeout", self.timeout)

        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button = QPushButton("Stop")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.stop_scan)
        self.save_button = QPushButton("Save Scan…")
        self.save_button.clicked.connect(self.save_scan)
        self.auto_save = QCheckBox("Auto-save last scan")
        self.auto_save.setChecked(True)
        self.history = QComboBox()
        self.history.setMinimumWidth(320)
        self.history.currentIndexChanged.connect(self._history_chosen)
        scan_actions = QHBoxLayout()
        scan_actions.addWidget(self.scan_button)
        scan_actions.addWidget(self.cancel_button)
        scan_actions.addWidget(self.save_button)
        scan_actions.addWidget(self.auto_save)
        scan_actions.addStretch()
        scan_actions.addWidget(QLabel("Previous scans"))
        scan_actions.addWidget(self.history, 1)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["IP", "DNS", "RTT (ms)", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.status = QLabel("Enter any reachable remote or local IPv4 subnet.")

        add_responders = QPushButton("Add responders")
        add_responders.clicked.connect(lambda: self._emit_targets("responders"))
        add_all = QPushButton("Add all")
        add_all.clicked.connect(lambda: self._emit_targets("all"))
        add_selected = QPushButton("Add selected")
        add_selected.clicked.connect(lambda: self._emit_targets("selected"))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(add_responders)
        actions.addWidget(add_all)
        actions.addWidget(add_selected)
        actions.addStretch()
        actions.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(scan_actions)
        layout.addWidget(self.table)
        layout.addWidget(self.status)
        layout.addLayout(actions)
        self._refresh_history()

    def _validated_hosts(self) -> list[str] | None:
        try:
            hosts = expand_ipv4_spec(self.spec.text(), maximum=1022)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid scan range", str(exc))
            return None
        if len(hosts) > 254:
            answer = QMessageBox.question(
                self,
                "Confirm larger scan",
                f"This scan contains {len(hosts)} addresses. Continue? "
                "TracePlotter permits at most a /22 (1022 usable hosts).",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return hosts

    def start_scan(self) -> None:
        hosts = self._validated_hosts()
        if hosts is None:
            return
        self._stop.clear()
        self._results.clear()
        self._dns.clear()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.save_button.setEnabled(False)
        self.status.setText(f"Scanning {len(hosts)} addresses…")
        sweeper = SubnetSweeper(self.workers.value(), self.timeout.value())

        def work() -> None:
            sweeper.sweep(hosts, self._signals.result.emit, self._stop)
            self._signals.finished.emit()

        threading.Thread(target=work, name="subnet-scan", daemon=True).start()

    def stop_scan(self) -> None:
        self._stop.set()
        self.status.setText("Stopping scan…")

    def _append_result(self, result: ProbeResult) -> None:
        if result.alive and result.responder is None:
            result = ProbeResult(
                result.host, result.alive, result.rtt_ms, result.host, result.reached_target, result.error
            )
        self._results[result.host] = result
        discovered = reverse_dns(result.host) if result.alive else ""
        dns = self._hostnames.resolve(result.host, discovered)
        self._dns[result.host] = dns
        self._insert_result_row(result, dns)
        self.status.setText(f"Received {len(self._results)} of the scheduled results…")

    def _insert_result_row(self, result: ProbeResult, dns: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [result.host, dns, _latency(result.rtt_ms), "Alive" if result.alive else "No reply"]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.ItemDataRole.UserRole, result.host)
            if result.alive:
                item.setForeground(QColor("#18864b"))
            self.table.setItem(row, column, item)

    def _scan_finished(self) -> None:
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.save_button.setEnabled(bool(self._results))
        self.table.setSortingEnabled(True)
        alive = sum(result.alive for result in self._results.values())
        suffix = " (stopped)" if self._stop.is_set() else ""
        note = f"Scan complete{suffix}: {alive} responders, {len(self._results)} results."
        if self._results and self.auto_save.isChecked():
            try:
                saved = self._persist_scan(as_last=True)
                note += f" Auto-saved as “{saved.name}”."
                self._refresh_history(select_id=saved.id)
            except OSError as exc:
                note += f" Auto-save failed: {exc}"
        self.status.setText(note)

    def _persist_scan(self, *, as_last: bool = False, name: str | None = None):
        return self._library.save(
            spec=self.spec.text().strip(),
            results=self._results,
            dns_names=self._dns,
            hostnames=self._hostnames.snapshot(self._results.keys()),
            workers=self.workers.value(),
            timeout=self.timeout.value(),
            stopped=self._stop.is_set(),
            name=name,
            as_last=as_last,
        )

    def save_scan(self) -> None:
        if not self._results:
            QMessageBox.information(self, "Nothing to save", "Run a scan before saving.")
            return
        default = f"{self.spec.text().strip()} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        name, ok = QInputDialog.getText(self, "Save Scan", "Scan name:", text=default)
        if not ok or not name.strip():
            return
        try:
            saved = self._persist_scan(name=name.strip())
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self._refresh_history(select_id=saved.id)
        self.status.setText(f"Saved “{saved.name}” ({saved.alive_count}/{len(saved.results)} up).")

    def _refresh_history(self, select_id: str | None = None) -> None:
        self._loading_history = True
        self.history.clear()
        self.history.addItem("Load previous scan…", "")
        for scan in self._library.list_scans():
            self.history.addItem(scan.label, scan.id)
        if select_id:
            index = self.history.findData(select_id)
            if index >= 0:
                self.history.setCurrentIndex(index)
        self._loading_history = False
        self.save_button.setEnabled(bool(self._results))

    def _history_chosen(self, index: int) -> None:
        if self._loading_history or index <= 0:
            return
        scan_id = self.history.itemData(index)
        if not scan_id:
            return
        try:
            scan = self._library.load(str(scan_id))
        except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            self._refresh_history()
            return
        results, dns_names = probe_results_from_saved(scan)
        imported = self._hostnames.merge(scan.hostnames)
        self._results = results
        self._dns = {
            host: self._hostnames.resolve(host, dns_names.get(host, "")) for host in results
        }
        self.spec.setText(scan.spec)
        self.workers.setValue(scan.workers)
        self.timeout.setValue(scan.timeout)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        def host_key(host: str) -> tuple:
            try:
                return (0, *(int(part) for part in host.split(".")))
            except ValueError:
                return (1, host)

        for host in sorted(results, key=host_key):
            self._insert_result_row(results[host], self._dns.get(host, ""))
        self.table.setSortingEnabled(True)
        self.save_button.setEnabled(bool(self._results))
        extra = f" Restored {imported} hostname(s)." if imported else ""
        self.status.setText(
            f"Loaded “{scan.name}”: {scan.alive_count} responders, {len(scan.results)} results.{extra}"
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_history()

    def _emit_targets(self, mode: str) -> None:
        if mode == "responders":
            hosts = [host for host, result in self._results.items() if result.alive]
        elif mode == "selected":
            hosts = sorted(
                {
                    item.data(Qt.ItemDataRole.UserRole)
                    for item in self.table.selectedItems()
                    if item.data(Qt.ItemDataRole.UserRole)
                },
                key=ipaddress.IPv4Address,
            )
        else:
            hosts = list(self._results)
        if not hosts:
            QMessageBox.information(self, "No targets", "There are no matching scan results to add.")
            return
        self.add_targets.emit(hosts)

    def reject(self) -> None:
        self.stop_scan()
        super().reject()


class MainSignals(QObject):
    updated = Signal(str)


class TraceHistoryDelegate(QStyledItemDelegate):
    """Reserve space on the right for a delete affordance in the popup list."""

    DELETE_WIDTH = 28

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        trace_id = index.data(Qt.ItemDataRole.UserRole)
        if trace_id:
            opt.rect = option.rect.adjusted(0, 0, -self.DELETE_WIDTH, 0)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if not trace_id:
            return
        theme = current_theme()
        x_rect = QRect(
            option.rect.right() - self.DELETE_WIDTH,
            option.rect.top(),
            self.DELETE_WIDTH,
            option.rect.height(),
        )
        painter.save()
        painter.setPen(QColor(theme.muted))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(x_rect, int(Qt.AlignmentFlag.AlignCenter), "×")
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        if index.data(Qt.ItemDataRole.UserRole):
            hint.setWidth(hint.width() + self.DELETE_WIDTH)
        return hint


class TraceHistoryCombo(QComboBox):
    """Previous-traces dropdown with a clickable × to delete each saved entry."""

    delete_requested = Signal(str, str)  # trace_id, label

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setItemDelegate(TraceHistoryDelegate(self))
        self.view().viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.view().viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            mouse = event
            if isinstance(mouse, QMouseEvent) and mouse.button() == Qt.MouseButton.LeftButton:
                pos = mouse.position().toPoint()
                index = self.view().indexAt(pos)
                if index.isValid():
                    trace_id = index.data(Qt.ItemDataRole.UserRole)
                    if trace_id:
                        rect = self.view().visualRect(index)
                        x_rect = QRect(
                            rect.right() - TraceHistoryDelegate.DELETE_WIDTH,
                            rect.top(),
                            TraceHistoryDelegate.DELETE_WIDTH,
                            rect.height(),
                        )
                        if x_rect.contains(pos):
                            label = str(index.data(Qt.ItemDataRole.DisplayRole) or trace_id)
                            self.hidePopup()
                            self.delete_requested.emit(str(trace_id), label)
                            return True
        return super().eventFilter(watched, event)


class OptionsDialog(QDialog):
    """App customization: theme and toolbar layout."""

    theme_changed = Signal(str)

    def __init__(self, prefs: Preferences, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.resize(420, 260)
        self.prefs = prefs

        theme_box = QVBoxLayout()
        self.light = QRadioButton("Light")
        self.dark = QRadioButton("Dark")
        if prefs.theme == "dark":
            self.dark.setChecked(True)
        else:
            self.light.setChecked(True)
        theme_box.addWidget(self.light)
        theme_box.addWidget(self.dark)

        form = QFormLayout()
        form.addRow("Theme", theme_box)

        reset_toolbar = QPushButton("Reset toolbar layout")
        reset_toolbar.clicked.connect(self._reset_toolbar)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(reset_toolbar)
        layout.addStretch()
        layout.addWidget(buttons)

        self.light.toggled.connect(self._preview_theme)
        self.dark.toggled.connect(self._preview_theme)

    def selected_theme(self) -> str:
        return "dark" if self.dark.isChecked() else "light"

    def _preview_theme(self, checked: bool) -> None:
        if checked:
            self.theme_changed.emit(self.selected_theme())

    def _reset_toolbar(self) -> None:
        parent = self.parent()
        if isinstance(parent, MainWindow):
            parent.banner.reset_layout()
            QMessageBox.information(self, "Toolbar", "Toolbar layout reset to defaults.")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TracePlotter")
        self.resize(1280, 780)
        self.prefs = Preferences.load()
        set_theme(self.prefs.theme)
        self.hostnames = HostnameBook()
        self.store = SampleStore(hostname_lookup=self.hostnames.resolve)
        self.trace_library = TraceLibrary()
        self._loading_trace_history = False
        self._layout_edit = False
        self.tracers: dict[str, ContinuousTracer] = {}
        self.signals = MainSignals()
        self.signals.updated.connect(self._target_updated)
        self.scan_dialog: RemoteSubnetScanDialog | None = None

        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("Hostname or IP address")
        self.target_input.returnPressed.connect(self.add_input_target)
        add_button = QPushButton("Add / Start")
        add_button.clicked.connect(self.add_input_target)
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop_current)
        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(self.reset_current)
        save_trace_button = QPushButton("Save Trace…")
        save_trace_button.clicked.connect(self.save_trace)
        self.action_auto_save_trace = QAction("Auto-save last trace", self)
        self.action_auto_save_trace.setCheckable(True)
        self.action_auto_save_trace.setChecked(self.prefs.auto_save_trace)
        self.action_auto_save_trace.toggled.connect(self._auto_save_trace_toggled)
        self.action_show_unresolved = QAction("Show unresolved hops", self)
        self.action_show_unresolved.setCheckable(True)
        self.action_show_unresolved.setChecked(self.prefs.show_unresolved)
        self.action_show_unresolved.setToolTip("When unchecked, hide hops that only show * (no IP yet).")
        self.action_show_unresolved.toggled.connect(self._unresolved_toggled)
        self.action_hide_unresponsive = QAction("Hide unresponsive hosts", self)
        self.action_hide_unresponsive.setCheckable(True)
        self.action_hide_unresponsive.setChecked(self.prefs.hide_unresponsive)
        self.action_hide_unresponsive.setToolTip(
            "Hide down hosts from the list; scanning continues so they reappear if they return."
        )
        self.action_hide_unresponsive.toggled.connect(self._hide_unresponsive_toggled)
        self.sort_by_ip_action = QAction("Sort by IP", self)
        self.sort_by_ip_action.setCheckable(True)
        self.sort_by_hostname_action = QAction("Sort by hostname", self)
        self.sort_by_hostname_action.setCheckable(True)
        self.target_sort_group = QActionGroup(self)
        self.target_sort_group.setExclusive(True)
        self.target_sort_group.addAction(self.sort_by_ip_action)
        self.target_sort_group.addAction(self.sort_by_hostname_action)
        if self.prefs.target_sort == "hostname":
            self.sort_by_hostname_action.setChecked(True)
        else:
            self.sort_by_ip_action.setChecked(True)
        self.target_sort_group.triggered.connect(self._target_sort_action_triggered)
        self.trace_history = TraceHistoryCombo()
        self.trace_history.setMinimumWidth(260)
        self.trace_history.currentIndexChanged.connect(self._trace_history_chosen)
        self.trace_history.delete_requested.connect(self._delete_trace_from_history)
        scan_button = QPushButton("Subnet scan…")
        scan_button.clicked.connect(self.open_scan)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 60.0)
        self.interval.setValue(2.5)
        self.interval.setSuffix(" s")
        self.probe_timeout = QDoubleSpinBox()
        self.probe_timeout.setRange(0.2, 10.0)
        self.probe_timeout.setValue(1.0)
        self.probe_timeout.setSuffix(" s")

        self.target_input.setMinimumWidth(160)
        self.trace_history.setMinimumWidth(220)
        chips = {
            "target": ToolbarChip("target", _labeled_control("Target", self.target_input)),
            "add": ToolbarChip("add", add_button),
            "stop": ToolbarChip("stop", stop_button),
            "reset": ToolbarChip("reset", reset_button),
            "save_trace": ToolbarChip("save_trace", save_trace_button),
            "trace_history": ToolbarChip(
                "trace_history", _labeled_control("Previous traces", self.trace_history)
            ),
            "interval": ToolbarChip("interval", _labeled_control("Interval", self.interval)),
            "timeout": ToolbarChip("timeout", _labeled_control("Timeout", self.probe_timeout)),
            "subnet_scan": ToolbarChip("subnet_scan", scan_button),
        }
        default_rows = [
            [
                "target",
                "add",
                "stop",
                "reset",
                "save_trace",
                "trace_history",
            ],
            ["interval", "timeout", "subnet_scan"],
        ]
        self.banner = DualBanner(chips, default_rows)
        self.banner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.banner.customContextMenuRequested.connect(self._banner_context_menu)

        self.targets = QTableWidget(0, 2)
        self.targets.setObjectName("hostTargets")
        self.targets.setMinimumWidth(240)
        self.targets.verticalHeader().setVisible(False)
        self.targets.setShowGrid(False)
        self.targets.setAlternatingRowColors(True)
        self.targets.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.targets.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.targets.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.targets.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.targets.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.targets.setWordWrap(False)
        self.targets.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = CompactHostHeader(self.targets)
        self.targets.setHorizontalHeader(header)
        for column in range(2):
            blank = QTableWidgetItem("")
            blank.setData(Qt.ItemDataRole.DisplayRole, "")
            self.targets.setHorizontalHeaderItem(column, blank)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.resizeSection(0, self.prefs.host_ip_width)
        header.resizeSection(1, self.prefs.host_hostname_width)
        header.sectionResized.connect(self._host_columns_resized)
        header.sectionClicked.connect(self._host_header_clicked)
        sort_section = 1 if self.prefs.target_sort == "hostname" else 0
        header.setSortIndicator(sort_section, Qt.SortOrder.AscendingOrder)
        self.targets.itemSelectionChanged.connect(self._target_selection_changed)
        self.targets.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.targets.customContextMenuRequested.connect(self._target_context_menu)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Hop", "Count", "IP", "Hostname", "Avg", "Min", "Cur", "PL%"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(0, HopCircleDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._hop_context_menu)
        self.focus = FocusChart(self.table)
        self.chart = TimelineChart()
        self.time_window = QComboBox()
        for label, seconds in TIME_WINDOW_CHOICES:
            self.time_window.addItem(label, seconds)
        # Default to 15 min (PingPlotter-like middle option).
        self.time_window.setCurrentIndex(3)
        self.time_window.currentIndexChanged.connect(self._time_window_changed)
        self.chart.set_window(int(self.time_window.currentData()), self.time_window.currentText())

        legend = QWidget()
        legend.setObjectName("latencyLegend")
        legend_row = QHBoxLayout(legend)
        legend_row.setContentsMargins(6, 2, 6, 2)
        legend_row.setSpacing(8)
        for color, label in (
            ("#7ac943", "0–100 ms"),
            ("#f5c542", "101–200 ms"),
            ("#e85d5d", "201+ ms"),
        ):
            swatch = QLabel("●")
            swatch.setStyleSheet(f"QLabel {{ color: {color}; font-size: 16px; background: transparent; }}")
            legend_row.addWidget(swatch)
            legend_row.addWidget(QLabel(label))

        chart_header = QWidget()
        chart_header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        chart_header_row = QHBoxLayout(chart_header)
        chart_header_row.setContentsMargins(0, 0, 0, 0)
        chart_header_row.addWidget(QLabel("Time graph"))
        chart_header_row.addWidget(legend)
        chart_header_row.addStretch()
        chart_header_row.addWidget(QLabel("Show"))
        chart_header_row.addWidget(self.time_window)

        chart_body = QWidget()
        chart_layout = QVBoxLayout(chart_body)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(4)
        chart_layout.addWidget(chart_header)
        chart_layout.addWidget(self.chart, 1)

        self.pane_shells = {
            "hosts": PaneShell("hosts", self.targets),
            "hops": PaneShell("hops", self.table),
            "focus": PaneShell("focus", self.focus),
            "timeline": PaneShell("timeline", chart_body),
        }
        for shell in self.pane_shells.values():
            shell.set_swap_callback(self._swap_panes)
            shell.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            shell.customContextMenuRequested.connect(self._banner_context_menu)

        self.hops_pane = QSplitter(Qt.Orientation.Horizontal)
        self.hops_pane.setChildrenCollapsible(False)
        self.right_pane = QSplitter(Qt.Orientation.Vertical)
        self.right_pane.setChildrenCollapsible(False)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self._pane_slots = self._load_pane_slots()
        self._apply_pane_slots()

        center = QWidget()
        center.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        center.customContextMenuRequested.connect(self._banner_context_menu)
        layout = QVBoxLayout(center)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(6)
        layout.addWidget(self.banner, 0)
        layout.addWidget(self.main_splitter, 1)
        self.setCentralWidget(center)
        self.apply_theme(self.prefs.theme)
        self.set_layout_edit(False)
        self.statusBar().showMessage(
            "Ready — continuous traceroute samples (green ≤100 ms, yellow ≤200, red 201+)."
        )
        self._refresh_trace_history()

    def apply_theme(self, key: str) -> None:
        theme = set_theme(key)
        self.setStyleSheet(theme.stylesheet)
        self.focus.update()
        self.chart.update()
        self.table.viewport().update()
        self._paint_target_statuses()
        current = self._current_target()
        if current:
            self.refresh(current)

    def open_options(self) -> None:
        previous = self.prefs.theme
        dialog = OptionsDialog(self.prefs, self)
        dialog.theme_changed.connect(self.apply_theme)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.prefs.theme = dialog.selected_theme()
            self.prefs.save()
            self.apply_theme(self.prefs.theme)
            self.statusBar().showMessage(f"Theme set to {THEMES[self.prefs.theme].label}.")
        else:
            self.apply_theme(previous)

    def set_layout_edit(self, enabled: bool) -> None:
        self._layout_edit = enabled
        self.banner.set_layout_edit(enabled)
        for shell in self.pane_shells.values():
            shell.set_layout_edit(enabled)
        message = (
            "Layout edit on — drag ⋮⋮ handles to rearrange toolbar items and panes."
            if enabled
            else "Layout edit off."
        )
        self.statusBar().showMessage(message)

    def _default_pane_slots(self) -> dict[str, str]:
        return {"left": "hosts", "hops": "hops", "focus": "focus", "timeline": "timeline"}

    def _load_pane_slots(self) -> dict[str, str]:
        path = default_panes_path()
        defaults = self._default_pane_slots()
        if not path.exists():
            return defaults
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            slots = data.get("slots") or {}
            merged = dict(defaults)
            for key in defaults:
                value = str(slots.get(key) or "")
                if value in self.pane_shells:
                    merged[key] = value
            # Ensure every pane appears exactly once.
            used = list(merged.values())
            missing = [pane for pane in self.pane_shells if pane not in used]
            seen: set[str] = set()
            for key, value in list(merged.items()):
                if value in seen or value not in self.pane_shells:
                    merged[key] = missing.pop(0) if missing else value
                seen.add(merged[key])
            return merged
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return defaults

    def _persist_pane_slots(self) -> None:
        path = default_panes_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"slots": self._pane_slots}, indent=2) + "\n", encoding="utf-8")

    def _apply_pane_slots(self) -> None:
        # Detach all shells before rebuilding splitter tree.
        for shell in self.pane_shells.values():
            shell.setParent(None)
        while self.hops_pane.count():
            self.hops_pane.widget(0).setParent(None)
        while self.right_pane.count():
            self.right_pane.widget(0).setParent(None)
        while self.main_splitter.count():
            self.main_splitter.widget(0).setParent(None)

        left = self.pane_shells[self._pane_slots["left"]]
        hops = self.pane_shells[self._pane_slots["hops"]]
        focus = self.pane_shells[self._pane_slots["focus"]]
        timeline = self.pane_shells[self._pane_slots["timeline"]]

        self.hops_pane.addWidget(hops)
        self.hops_pane.addWidget(focus)
        self.hops_pane.setStretchFactor(0, 3)
        self.hops_pane.setStretchFactor(1, 1)

        self.right_pane.addWidget(self.hops_pane)
        self.right_pane.addWidget(timeline)
        self.right_pane.setStretchFactor(0, 0)
        self.right_pane.setStretchFactor(1, 1)
        self.right_pane.setSizes([320, 280])

        self.main_splitter.addWidget(left)
        self.main_splitter.addWidget(self.right_pane)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

    def _swap_panes(self, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        slot_of = {pane_id: slot for slot, pane_id in self._pane_slots.items()}
        source_slot = slot_of.get(source_id)
        target_slot = slot_of.get(target_id)
        if not source_slot or not target_slot:
            return
        self._pane_slots[source_slot], self._pane_slots[target_slot] = (
            self._pane_slots[target_slot],
            self._pane_slots[source_slot],
        )
        self._apply_pane_slots()
        self._persist_pane_slots()
        self.set_layout_edit(self._layout_edit)

    def _reset_pane_layout(self) -> None:
        self._pane_slots = self._default_pane_slots()
        self._apply_pane_slots()
        self._persist_pane_slots()
        self.set_layout_edit(self._layout_edit)

    def _banner_context_menu(self, pos) -> None:
        menu = QMenu(self)
        options = QAction("Options…", self)
        options.triggered.connect(self.open_options)
        change_layout = QAction("Change layout", self)
        change_layout.setCheckable(True)
        change_layout.setChecked(self._layout_edit)
        change_layout.toggled.connect(self.set_layout_edit)
        reset_toolbar = QAction("Reset toolbar layout", self)
        reset_toolbar.triggered.connect(self.banner.reset_layout)
        reset_panes = QAction("Reset pane layout", self)
        reset_panes.triggered.connect(self._reset_pane_layout)
        menu.addAction(options)
        menu.addSeparator()
        menu.addAction(self.action_show_unresolved)
        menu.addAction(self.action_hide_unresponsive)
        menu.addAction(self.action_auto_save_trace)
        sort_menu = menu.addMenu("Sort hosts")
        sort_menu.addAction(self.sort_by_ip_action)
        sort_menu.addAction(self.sort_by_hostname_action)
        menu.addSeparator()
        menu.addAction(change_layout)
        menu.addAction(reset_toolbar)
        menu.addAction(reset_panes)
        sender = self.sender()
        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(pos))
        else:
            menu.exec(self.mapToGlobal(pos))

    def add_input_target(self) -> None:
        value = self.target_input.text().strip()
        if value:
            self.add_targets([value])
            self.target_input.clear()

    def add_targets(self, targets: Iterable[str], *, start: bool = True) -> None:
        added = 0
        skipped: list[str] = []
        for target in targets:
            target = target.strip()
            if not target or target in self.tracers:
                continue
            resolved = resolve_ipv4(target)
            if resolved is None:
                skipped.append(target)
                continue
            if not self._looks_like_ipv4(target) and not self.hostnames.get(resolved):
                try:
                    self.hostnames.set(resolved, target)
                except ValueError:
                    pass
            tracer = ContinuousTracer(
                target,
                self.store,
                self.signals.updated.emit,
                interval=self.interval.value(),
                timeout=self.probe_timeout.value(),
            )
            self.tracers[target] = tracer
            self._insert_target_row(target, resolved_ip=resolved)
            if start:
                tracer.start()
            added += 1
        self._reorder_targets()
        self._paint_target_statuses()
        if self.targets.currentRow() < 0:
            self._select_first_visible_target()
        if skipped:
            QMessageBox.warning(
                self,
                "Could not resolve",
                "No IPv4 address for:\n" + "\n".join(f"• {name}" for name in skipped),
            )
        if start and added:
            self.statusBar().showMessage(f"Started {added} target(s).")
        elif start and not added and not skipped:
            self.statusBar().showMessage("No new targets to start.")

    def _insert_target_row(self, target: str, resolved_ip: str | None = None) -> int:
        row = self.targets.rowCount()
        self.targets.insertRow(row)
        display_ip = resolved_ip or target
        if self._looks_like_ipv4(target):
            display_ip = target
            name = self.hostnames.get(target) or ""
        else:
            name = target
            display_ip = resolved_ip or target
        if name == display_ip:
            name = ""
        ip_item = QTableWidgetItem(display_ip)
        ip_item.setData(Qt.ItemDataRole.UserRole, target)
        ip_item.setFlags(ip_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        host_item = QTableWidgetItem(name)
        host_item.setFlags(host_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        color = QColor(current_theme().text)
        ip_item.setForeground(color)
        host_item.setForeground(color)
        self.targets.setItem(row, 0, ip_item)
        self.targets.setItem(row, 1, host_item)
        self.targets.setRowHeight(row, 24)
        return row

    def _target_key(self, item: QTableWidgetItem | None) -> str:
        if item is None:
            return ""
        key = item.data(Qt.ItemDataRole.UserRole)
        if key:
            return str(key)
        # IP column text, or pair with column 0 when hostname cell is selected.
        if item.column() == 0:
            return item.text().strip()
        ip_item = self.targets.item(item.row(), 0)
        if ip_item is not None:
            key = ip_item.data(Qt.ItemDataRole.UserRole)
            return str(key) if key else ip_item.text().strip()
        return ""

    def _target_key_at(self, row: int) -> str:
        return self._target_key(self.targets.item(row, 0))

    def _current_target(self) -> str:
        row = self.targets.currentRow()
        return self._target_key_at(row) if row >= 0 else ""

    def _looks_like_ipv4(self, value: str) -> bool:
        try:
            ipaddress.IPv4Address(value)
            return True
        except ValueError:
            return False

    def _current_sort_mode(self) -> str:
        return "hostname" if self.sort_by_hostname_action.isChecked() else "ip"

    def _target_sort_key_for(self, target: str) -> tuple:
        return target_sort_key(target, self.hostnames.get(target), self._current_sort_mode())

    def _reorder_targets(self) -> None:
        current = self._current_target()
        self.targets.blockSignals(True)
        keys = [self._target_key_at(row) for row in range(self.targets.rowCount())]
        keys.sort(key=self._target_sort_key_for)
        self.targets.setRowCount(0)
        for target in keys:
            self._insert_target_row(target)
        restored = False
        for row in range(self.targets.rowCount()):
            if self.targets.isRowHidden(row):
                continue
            if self._target_key_at(row) == current:
                self.targets.setCurrentCell(row, 0)
                restored = True
                break
        if not restored:
            self._select_first_visible_target()
        self.targets.blockSignals(False)

    def _select_first_visible_target(self) -> None:
        for row in range(self.targets.rowCount()):
            if not self.targets.isRowHidden(row):
                self.targets.setCurrentCell(row, 0)
                return

    def _host_columns_resized(self, index: int, _old: int, new: int) -> None:
        if index == 0:
            self.prefs.host_ip_width = max(60, new)
        elif index == 1:
            self.prefs.host_hostname_width = max(60, new)
        else:
            return
        self.prefs.save()

    def _hide_unresponsive_toggled(self, checked: bool) -> None:
        self.prefs.hide_unresponsive = checked
        self.prefs.save()
        self._paint_target_statuses()
        row = self.targets.currentRow()
        if row < 0 or self.targets.isRowHidden(row):
            self._select_first_visible_target()
            target = self._current_target()
            if target:
                self.refresh(target)

    def _host_header_clicked(self, section: int) -> None:
        mode = "hostname" if section == 1 else "ip"
        action = self.sort_by_hostname_action if mode == "hostname" else self.sort_by_ip_action
        if action.isChecked():
            self._apply_target_sort(mode)
        else:
            action.setChecked(True)

    def _target_sort_action_triggered(self, action: QAction) -> None:
        mode = "hostname" if action is self.sort_by_hostname_action else "ip"
        self._apply_target_sort(mode)

    def _apply_target_sort(self, mode: str) -> None:
        if mode not in ("ip", "hostname"):
            mode = "ip"
        self.prefs.target_sort = mode
        self.prefs.save()
        section = 1 if mode == "hostname" else 0
        self.targets.horizontalHeader().setSortIndicator(section, Qt.SortOrder.AscendingOrder)
        self._reorder_targets()
        self._paint_target_statuses()

    def _target_selection_changed(self) -> None:
        self.refresh(self._current_target())

    def stop_current(self) -> None:
        target = self._current_target()
        if target in self.tracers:
            self.tracers[target].stop()
            self.statusBar().showMessage(f"Stopped {target}.")

    def reset_current(self) -> None:
        target = self._current_target()
        if target:
            self.store.reset(target)
            self.refresh(target)

    def _time_window_changed(self, _index: int) -> None:
        seconds = int(self.time_window.currentData())
        self.chart.set_window(seconds, self.time_window.currentText())
        # Keep historical pan position when the window width changes.
        target = self._current_target()
        if target:
            self.refresh(target)

    def _selected_window_seconds(self) -> int:
        data = self.time_window.currentData()
        return int(data) if data is not None else 15 * 60

    def _unresolved_toggled(self, checked: bool) -> None:
        self.prefs.show_unresolved = checked
        self.prefs.save()
        target = self._current_target()
        if target:
            self.refresh(target)

    def _auto_save_trace_toggled(self, checked: bool) -> None:
        self.prefs.auto_save_trace = checked
        self.prefs.save()

    def _visible_hops(self, hops: list[HopStats], target: str) -> list[HopStats]:
        dest_ips = {target}
        tracer = self.tracers.get(target)
        if tracer is not None and tracer.target_ip:
            dest_ips.add(tracer.target_ip)
        if self.action_show_unresolved.isChecked():
            visible = list(hops)
        else:
            visible = [
                hop
                for hop in hops
                if hop.resolved or hop.ip in dest_ips
            ]
        # Always keep the scanned destination as the final row when it's down.
        if not any(hop.ip in dest_ips for hop in visible):
            dest_ip = next(iter(dest_ips))
            if self._looks_like_ipv4(target):
                dest_ip = target
            elif tracer is not None:
                dest_ip = tracer.target_ip
            hop_num = (max((hop.hop for hop in hops), default=0) + 1)
            placeholder = HopStats(
                hop=hop_num,
                ip=dest_ip,
                dns=self.hostnames.resolve(dest_ip, ""),
                sent=1,
                received=0,
                last_ms=None,
            )
            visible.append(placeholder)
        return visible

    def _hop_context_menu(self, pos: QPoint) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        hop_item = self.table.item(item.row(), 0)
        ip_item = self.table.item(item.row(), 2)
        if hop_item is None or ip_item is None:
            return
        hop = int(hop_item.text())
        ip = ip_item.text()
        menu = QMenu(self)
        set_action = QAction("Set hostname…", self)
        set_action.triggered.connect(lambda: self._set_hostname_for_row(hop, ip))
        menu.addAction(set_action)
        if ip and ip != "*" and self.hostnames.get(ip):
            clear_action = QAction("Clear manual hostname", self)
            clear_action.triggered.connect(lambda: self._clear_hostname_for_row(hop, ip))
            menu.addAction(clear_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _prompt_hostname(self, ip: str) -> str | None:
        if not ip or ip == "*":
            QMessageBox.information(
                self,
                "No IP yet",
                "This entry has no IP address yet. Wait until it resolves, then set a hostname.",
            )
            return None
        current = self.hostnames.get(ip) or ""
        name, ok = QInputDialog.getText(
            self,
            "Set hostname",
            f"Hostname for {ip}:",
            text=current,
        )
        if not ok or not name.strip():
            return None
        try:
            self.hostnames.set(ip, name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid hostname", str(exc))
            return None
        return name.strip()

    def _set_hostname_for_row(self, hop: int, ip: str) -> None:
        target = self._current_target()
        if not target:
            return
        name = self._prompt_hostname(ip)
        if not name:
            return
        self.store.set_hop_hostname(target, hop, name)
        self._paint_target_statuses()
        self.refresh(target)

    def _clear_hostname_for_row(self, hop: int, ip: str) -> None:
        target = self._current_target()
        if not target or not ip or ip == "*":
            return
        self.hostnames.clear(ip)
        discovered = reverse_dns(ip)
        self.store.set_hop_hostname(target, hop, discovered)
        self._paint_target_statuses()
        self.refresh(target)

    def _target_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        item = self.targets.itemAt(pos)
        target = self._target_key(item) if item is not None else ""
        if target:
            set_action = QAction("Set hostname…", self)
            set_action.triggered.connect(lambda: self._set_hostname_for_target(target))
            menu.addAction(set_action)
            if self.hostnames.get(target):
                clear_action = QAction("Clear manual hostname", self)
                clear_action.triggered.connect(lambda: self._clear_hostname_for_target(target))
                menu.addAction(clear_action)
            menu.addSeparator()
        menu.addAction(self.action_hide_unresponsive)
        sort_menu = menu.addMenu("Sort hosts")
        sort_menu.addAction(self.sort_by_ip_action)
        sort_menu.addAction(self.sort_by_hostname_action)
        menu.exec(self.targets.viewport().mapToGlobal(pos))

    def _set_hostname_for_target(self, target: str) -> None:
        name = self._prompt_hostname(target)
        if not name:
            return
        # If this IP also appears as a hop under the current target, refresh that row too.
        if self._current_sort_mode() == "hostname":
            self._reorder_targets()
        self._paint_target_statuses()
        current = self._current_target()
        if current:
            for hop in self.store.hops(current):
                if hop.ip == target:
                    self.store.set_hop_hostname(current, hop.hop, name)
            self.refresh(current)

    def _clear_hostname_for_target(self, target: str) -> None:
        if not target:
            return
        self.hostnames.clear(target)
        discovered = reverse_dns(target) if self._looks_like_ipv4(target) else ""
        current = self._current_target()
        if current:
            for hop in self.store.hops(current):
                if hop.ip == target:
                    self.store.set_hop_hostname(current, hop.hop, discovered)
            self.refresh(current)
        if self._current_sort_mode() == "hostname":
            self._reorder_targets()
        self._paint_target_statuses()

    def open_scan(self) -> None:
        self.scan_dialog = RemoteSubnetScanDialog(self, hostnames=self.hostnames)
        self.scan_dialog.add_targets.connect(self.add_targets)
        self.scan_dialog.finished.connect(lambda _code: self._paint_target_statuses())
        self.scan_dialog.show()

    def _target_updated(self, target: str) -> None:
        self._paint_target_statuses()
        if self._current_target() == target:
            self.refresh(target)

    def _paint_target_statuses(self) -> None:
        hide_down = self.action_hide_unresponsive.isChecked()
        current = self._current_target()
        for row in range(self.targets.rowCount()):
            ip_item = self.targets.item(row, 0)
            host_item = self.targets.item(row, 1)
            if ip_item is None:
                continue
            target = self._target_key(ip_item)
            tracer = self.tracers.get(target)
            resolved = tracer.target_ip if tracer is not None else resolve_ipv4(target)
            if self._looks_like_ipv4(target):
                display_ip = target
                name = self.hostnames.get(target) or ""
            else:
                display_ip = resolved or target
                name = target
            if name == display_ip:
                name = ""
            ip_item.setText(display_ip)
            if host_item is None:
                host_item = QTableWidgetItem(name)
                host_item.setFlags(host_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.targets.setItem(row, 1, host_item)
            else:
                host_item.setText(name)
            theme = current_theme()
            up = self.store.endpoint_up(target)
            if up is True:
                color = QColor(theme.up)
                bold = False
            elif up is False:
                color = QColor(theme.down)
                bold = True
            else:
                color = QColor(theme.text)
                bold = False
            for cell in (ip_item, host_item):
                cell.setForeground(color)
                font = cell.font()
                font.setBold(bold)
                cell.setFont(font)
            # Keep tracers running; only hide from the list.
            self.targets.setRowHidden(row, bool(hide_down and up is False))
        row = self.targets.currentRow()
        if row >= 0 and self.targets.isRowHidden(row):
            self._select_first_visible_target()
            new_target = self._current_target()
            if new_target and new_target != current:
                self.refresh(new_target)

    def refresh(self, target: str) -> None:
        if not target:
            self.table.setRowCount(0)
            self.focus.set_hops([])
            self.chart.set_points([])
            return
        hops = self._visible_hops(self.store.hops(target), target)
        self.table.setRowCount(len(hops))
        for row, hop in enumerate(hops):
            cur = hop.last_ms
            down = cur is None and hop.sent > 0
            badge_ms = 999.0 if down else (cur if cur is not None else hop.avg_ms)
            self.table.setItem(row, 0, HopBadgeItem(hop.hop, badge_ms))
            hostname = hop.dns
            values = [
                str(hop.sent),
                hop.ip,
                hostname,
                _latency(hop.avg_ms),
                _latency(hop.min_ms),
                _latency(cur),
                f"{hop.loss_percent:.1f}",
            ]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                theme = current_theme()
                if column == 3 and not value and hop.resolved:
                    item.setText("")
                    item.setForeground(QColor(theme.muted))
                    item.setToolTip("Right-click to set a hostname manually")
                if down and column in (1, 2, 3, 7):
                    item.setForeground(QColor(theme.down))
                if column in (4, 5, 6) and value:
                    try:
                        item.setBackground(_band_color(float(value), soft=True))
                    except ValueError:
                        pass
                if column == 7 and hop.loss_percent >= 50:
                    item.setForeground(QColor(theme.down))
                    item.setBackground(QColor(232, 93, 93, 40))
                if column == 3 and hop.resolved and self.hostnames.get(hop.ip):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setToolTip("Manual hostname (right-click to edit or clear)")
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 28)
        self.focus.set_hops(hops)
        # Full retained history so the chart can pan backward past the visible window.
        self.chart.set_points(self.store.timeline(target))
        self._paint_target_statuses()

    def _session_hostnames(self) -> dict[str, str]:
        ips: set[str] = set()
        for target in self.tracers:
            ips.add(target)
            for hop in self.store.hops(target):
                if hop.resolved:
                    ips.add(hop.ip)
        return self.hostnames.snapshot(ips)

    def _persist_trace(self, *, as_last: bool = False, name: str | None = None):
        targets = [self._target_key_at(row) for row in range(self.targets.rowCount())]
        targets = [target for target in targets if target]
        if not targets:
            raise ValueError("Add at least one target before saving.")
        return self.trace_library.save(
            targets=targets,
            state=self.store.export_state(targets),
            hostnames=self._session_hostnames(),
            interval=self.interval.value(),
            timeout=self.probe_timeout.value(),
            time_window_seconds=self._selected_window_seconds(),
            show_unresolved=self.action_show_unresolved.isChecked(),
            selected_target=self._current_target(),
            name=name,
            as_last=as_last,
        )

    def save_trace(self) -> None:
        try:
            target_keys = [
                self._target_key_at(row)
                for row in range(self.targets.rowCount())
                if self._target_key_at(row)
            ]
            if len(target_keys) == 1:
                default = target_keys[0]
            elif target_keys:
                default = f"{len(target_keys)} targets"
            else:
                default = self._current_target() or "trace"
            name, ok = QInputDialog.getText(self, "Save Trace", "Trace name:", text=default)
            if not ok or not name.strip():
                return
            saved = self._persist_trace(name=name.strip())
        except ValueError as exc:
            QMessageBox.information(self, "Nothing to save", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self._refresh_trace_history(select_id=saved.id)
        self.statusBar().showMessage(f"Saved trace “{saved.name}”.")

    def _delete_trace_from_history(self, trace_id: str, label: str) -> None:
        if not trace_id:
            return
        answer = QMessageBox.question(
            self,
            "Delete trace",
            f"Delete saved trace?\n\n{label}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.trace_library.delete(trace_id)
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
            self._refresh_trace_history()
            return
        self._refresh_trace_history()
        self.statusBar().showMessage("Deleted saved trace.")

    def _refresh_trace_history(self, select_id: str | None = None) -> None:
        self._loading_trace_history = True
        self.trace_history.clear()
        self.trace_history.addItem("Load previous trace…", "")
        for trace in self.trace_library.list_traces():
            self.trace_history.addItem(trace.label, trace.id)
        if select_id:
            index = self.trace_history.findData(select_id)
            if index >= 0:
                self.trace_history.setCurrentIndex(index)
        self._loading_trace_history = False

    def _trace_history_chosen(self, index: int) -> None:
        if self._loading_trace_history or index <= 0:
            return
        trace_id = self.trace_history.itemData(index)
        if not trace_id:
            return
        try:
            trace = self.trace_library.load(str(trace_id))
        except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            self._refresh_trace_history()
            return
        self._load_trace(trace)

    def _load_trace(self, trace) -> None:
        for tracer in self.tracers.values():
            tracer.stop()
        self.tracers.clear()
        self.targets.clear()
        self.hostnames.merge(trace.hostnames)
        self.store.import_state(trace.state)
        self.interval.setValue(trace.interval)
        self.probe_timeout.setValue(trace.timeout)
        self.action_show_unresolved.blockSignals(True)
        self.action_show_unresolved.setChecked(trace.show_unresolved)
        self.action_show_unresolved.blockSignals(False)
        # Restore time window if it matches a known choice.
        window_index = self.time_window.findData(trace.time_window_seconds)
        if window_index >= 0:
            self.time_window.blockSignals(True)
            self.time_window.setCurrentIndex(window_index)
            self.time_window.blockSignals(False)
            self.chart.set_window(trace.time_window_seconds, self.time_window.currentText())
        self.add_targets(trace.targets, start=True)
        if trace.selected_target:
            for row in range(self.targets.rowCount()):
                if self._target_key_at(row) == trace.selected_target:
                    self.targets.setCurrentCell(row, 0)
                    break
        self._paint_target_statuses()
        current = self._current_target()
        if current:
            self.refresh(current)
        self._refresh_trace_history(select_id=trace.id)
        self.statusBar().showMessage(
            f"Loaded trace “{trace.name}” ({len(trace.targets)} target(s)); probing resumed."
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.action_auto_save_trace.isChecked() and self.tracers:
            try:
                self._persist_trace(as_last=True)
            except (OSError, ValueError):
                pass
        for tracer in self.tracers.values():
            tracer.stop()
        if self.scan_dialog:
            self.scan_dialog.stop_scan()
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("TracePlotter")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()

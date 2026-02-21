from __future__ import annotations

import qtawesome as qta
from PyQt6.QtCore import QDate, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDateEdit,
  QFrame,
  QGridLayout,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QMainWindow,
  QProgressBar,
  QPushButton,
  QScrollArea,
  QSizePolicy,
  QSpinBox,
  QTableWidget,
  QTableWidgetItem,
  QTextEdit,
  QVBoxLayout,
  QWidget,
)

from gui.components import MarqueeComboBox, NeumorphicCard, WidgetFactory
from gui.styles import StyleSheet

# Spacing constants (px) from the design system
_SP = StyleSheet.SP_STD      # 16
_SM = StyleSheet.SP_SMALL    # 12
_MC = StyleSheet.SP_MICRO    #  8
_IC = StyleSheet.COLORS['text_primary']   # icon tint colour
_IC2 = StyleSheet.COLORS['text_secondary']


def _icon_title(icon_name: str, text: str) -> QWidget:
  """Create a section title widget with a leading qtawesome icon."""
  w = QWidget()
  w.setStyleSheet("background: transparent; border: none;")
  h = QHBoxLayout(w)
  h.setContentsMargins(0, 0, 0, 0)
  h.setSpacing(6)
  ic = QLabel()
  ic.setPixmap(qta.icon(icon_name, color=_IC).pixmap(QSize(16, 16)))
  ic.setStyleSheet("background: transparent; border: none;")
  h.addWidget(ic)
  h.addWidget(WidgetFactory.create_section_title(text))
  h.addStretch()
  return w


def _labelled_field(icon_name: str, label_text: str, field: QWidget) -> QVBoxLayout:
  """Return a VBoxLayout with an icon+label row above a field widget."""
  col = QVBoxLayout()
  col.setSpacing(2)
  lbl_row = QHBoxLayout()
  lbl_row.setContentsMargins(0, 0, 0, 0)
  lbl_row.setSpacing(4)
  ic = QLabel()
  ic.setPixmap(qta.icon(icon_name, color=_IC2).pixmap(QSize(12, 12)))
  ic.setStyleSheet("background: transparent; border: none;")
  lbl_row.addWidget(ic)
  lbl_row.addWidget(WidgetFactory.create_label(label_text, size=11))
  lbl_row.addStretch()
  col.addLayout(lbl_row)
  col.addWidget(field)
  return col


class MainWindow(QMainWindow):
  """
  Main application window with a dark-grey neumorphic layout.

  Layout structure:

  * **Top row** — two cards side-by-side.

    * Left card: Account dropdown, folder picker, Browse/Scan buttons.
    * Right card: Date pickers, hour/minute dropdowns, interval,
      Generate button.

  * **Middle row** — video table card (left) + action buttons card (right).
  * **Bottom** — Logger panel card.
  * **Status bar** — progress bar + counters.

  All sections use ``QGridLayout`` / ``QHBoxLayout`` with stretch
  factors and size policies so that the window resizes gracefully
  without overlapping.

  :param parent: Optional parent widget.
  :type parent: QWidget | None
  """

  WINDOW_TITLE: str = "TikTok Scheduler"

  # Thread-safe signal for appending log messages from any thread.
  # Qt's signal/slot mechanism automatically queues cross-thread
  # emissions so the actual GUI update always runs on the main thread.
  _log_signal = pyqtSignal(str, int)

  def __init__(self, parent: QWidget | None = None) -> None:
    """
    Build the full widget hierarchy.

    :param parent: Optional parent widget.
    :type parent: QWidget | None
    """
    super().__init__(parent)
    self.setWindowTitle(self.WINDOW_TITLE)

    # Connect log signal to the actual GUI update slot
    self._log_signal.connect(self._do_append_log)

    # Scrollable central widget so nothing clips at small sizes
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(
      f"background: {StyleSheet.COLORS['bg_base']}; border: none;"
    )
    self.setCentralWidget(scroll)

    container = QWidget()
    scroll.setWidget(container)

    self._root = QVBoxLayout(container)
    self._root.setSpacing(_SP)
    self._root.setContentsMargins(_SP, _SP, _SP, _SP)

    # Build sections top-to-bottom
    self._build_top_row()
    self._build_video_and_actions_row()
    self._build_logger_section()
    self._build_status_row()

  # ================================================================
  # TOP ROW  (two cards side-by-side)
  # ================================================================

  def _build_top_row(self) -> None:
    """
    Build the top row containing the Account/Folder card (left) and
    the Schedule Settings card (right).

    Uses a QHBoxLayout with stretch 1:1 so both cards share width
    equally and compress proportionally.
    """
    row = QHBoxLayout()
    row.setSpacing(_SP)

    # ---- Left card: Account + Folder ----
    left_card = NeumorphicCard()
    left_layout = QVBoxLayout(left_card)
    left_layout.setSpacing(_SM)
    left_layout.setContentsMargins(
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
    )

    left_layout.addWidget(_icon_title("fa5s.user-circle", "Account & Folder"))

    # Account label + row
    left_layout.addWidget(WidgetFactory.create_label("Account", size=11))
    acc_row = QHBoxLayout()
    acc_row.setSpacing(_MC)
    self.account_dropdown = WidgetFactory.create_dropdown()
    self.account_dropdown.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    acc_row.addWidget(self.account_dropdown)
    self.add_account_btn = WidgetFactory.create_icon_button("+")
    self.add_account_btn.setIcon(qta.icon("fa5s.user-plus", color="#FFFFFF"))
    self.add_account_btn.setIconSize(QSize(16, 16))
    self.add_account_btn.setText("")
    acc_row.addWidget(self.add_account_btn)
    left_layout.addLayout(acc_row)

    # Folder path row
    folder_row = QHBoxLayout()
    folder_row.setSpacing(_MC)
    self.folder_dropdown = MarqueeComboBox()
    self.folder_dropdown.setPlaceholderText("Select video folder...")
    self.folder_dropdown.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    folder_row.addWidget(self.folder_dropdown)
    self.browse_button = WidgetFactory.create_button("")
    self.browse_button.setIcon(qta.icon("fa5s.folder-open", color=_IC))
    self.browse_button.setIconSize(QSize(16, 16))
    self.browse_button.setToolTip("Browse folder")
    self.browse_button.setMinimumWidth(42)
    folder_row.addWidget(self.browse_button)
    self.scan_button = WidgetFactory.create_button("")
    self.scan_button.setIcon(qta.icon("fa5s.search", color=_IC))
    self.scan_button.setIconSize(QSize(16, 16))
    self.scan_button.setToolTip("Scan folder")
    self.scan_button.setMinimumWidth(42)
    folder_row.addWidget(self.scan_button)
    left_layout.addLayout(folder_row)

    self.file_count_label = WidgetFactory.create_status_label("Files found: 0")
    left_layout.addWidget(self.file_count_label)

    # Caption area (label above field)
    caption_lbl = QHBoxLayout()
    caption_lbl.setSpacing(4)
    caption_ic = QLabel()
    caption_ic.setPixmap(qta.icon("fa5s.pen", color=_IC2).pixmap(QSize(12, 12)))
    caption_ic.setStyleSheet("background: transparent; border: none;")
    caption_lbl.addWidget(caption_ic)
    caption_lbl.addWidget(WidgetFactory.create_label("Caption", size=11))
    caption_lbl.addStretch()
    left_layout.addLayout(caption_lbl)
    self.caption_input = WidgetFactory.create_text_area(
      "Custom caption (optional)...", min_height=60,
    )
    self.caption_input.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    left_layout.addWidget(self.caption_input)

    # Default caption preview (read-only, shows what will be sent)
    self.caption_preview = WidgetFactory.create_status_label(
      "Default: Cre: <videoid>"
    )
    left_layout.addWidget(self.caption_preview)

    # Tags area (label above field)
    tags_lbl = QHBoxLayout()
    tags_lbl.setSpacing(4)
    tags_ic = QLabel()
    tags_ic.setPixmap(qta.icon("fa5s.hashtag", color=_IC2).pixmap(QSize(12, 12)))
    tags_ic.setStyleSheet("background: transparent; border: none;")
    tags_lbl.addWidget(tags_ic)
    tags_lbl.addWidget(WidgetFactory.create_label("Tags", size=11))
    tags_lbl.addStretch()
    left_layout.addLayout(tags_lbl)
    self.hashtags_input = WidgetFactory.create_text_area(
      "#tag1 #tag2 #tag3...", min_height=60,
    )
    self.hashtags_input.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    left_layout.addWidget(self.hashtags_input)

    left_layout.addStretch()

    left_card.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    row.addWidget(left_card, 1)

    # ---- Right card: Schedule Settings ----
    right_card = NeumorphicCard()
    right_layout = QVBoxLayout(right_card)
    right_layout.setSpacing(_SM)
    right_layout.setContentsMargins(
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
    )

    right_layout.addWidget(_icon_title("fa5s.calendar-alt", "Schedule"))

    # Date row — labels above fields
    date_row = QHBoxLayout()
    date_row.setSpacing(_SM)
    self.start_date = WidgetFactory.create_date_input()
    date_row.addLayout(_labelled_field("fa5s.calendar", "From", self.start_date))
    end_qdate = QDate.currentDate().addMonths(1)
    self.end_date = WidgetFactory.create_date_input(end_qdate)
    date_row.addLayout(_labelled_field("fa5s.calendar-check", "To", self.end_date))
    right_layout.addLayout(date_row)

    # Time row — single letter labels above fields with icons
    time_row = QHBoxLayout()
    time_row.setSpacing(_MC)
    self.time_start_hour = WidgetFactory.create_hour_dropdown()
    time_row.addLayout(_labelled_field("fa5s.clock", "H", self.time_start_hour))
    self.time_start_minute = WidgetFactory.create_minute_dropdown()
    time_row.addLayout(_labelled_field("fa5s.clock", "M", self.time_start_minute))

    self.time_end_hour = WidgetFactory.create_hour_dropdown()
    self.time_end_hour.setCurrentText("23")
    time_row.addLayout(_labelled_field("fa5s.hourglass-end", "H", self.time_end_hour))
    self.time_end_minute = WidgetFactory.create_minute_dropdown()
    self.time_end_minute.setCurrentText("55")
    time_row.addLayout(_labelled_field("fa5s.hourglass-end", "M", self.time_end_minute))
    right_layout.addLayout(time_row)

    # Time validation warning (red text for invalid time selection)
    self.time_warning = WidgetFactory.create_warning_label()
    right_layout.addWidget(self.time_warning)

    # Interval + Limit — labels above fields with icons
    opts_row = QHBoxLayout()
    opts_row.setSpacing(_SM)
    self.interval_spin = WidgetFactory.create_spin_input(
      minimum=5, maximum=1440, value=15, suffix=" min"
    )
    self.interval_spin.setMinimumWidth(85)
    opts_row.addLayout(_labelled_field("fa5s.stopwatch", "Interval", self.interval_spin))

    self.limit_spin = WidgetFactory.create_spin_input(
      minimum=1, maximum=9999, value=1
    )
    self.limit_spin.setMinimumWidth(70)
    opts_row.addLayout(_labelled_field("fa5s.hashtag", "Limit", self.limit_spin))
    opts_row.addStretch()
    right_layout.addLayout(opts_row)

    # Generate button — bottom-left with icon
    gen_row = QHBoxLayout()
    self.generate_btn = WidgetFactory.create_button(
      " Generate", btn_class="primary"
    )
    self.generate_btn.setIcon(qta.icon("fa5s.cogs", color="#FFFFFF"))
    self.generate_btn.setIconSize(QSize(14, 14))
    self.generate_btn.setMinimumWidth(120)
    gen_row.addWidget(self.generate_btn)
    gen_row.addStretch()
    right_layout.addLayout(gen_row)

    # Validation warning
    self.schedule_warning = WidgetFactory.create_warning_label()
    right_layout.addWidget(self.schedule_warning)

    right_layout.addStretch()

    right_card.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    row.addWidget(right_card, 1)

    self._root.addLayout(row)

  # ================================================================
  # VIDEO TABLE + ACTION CARD  (side-by-side)
  # ================================================================

  def _build_video_and_actions_row(self) -> None:
    """
    Build the video table (left) and action buttons card (right)
    side-by-side in a single row.

    The video table card takes most of the width (stretch 3) while
    the action card sits on the right as a compact vertical panel
    (stretch 0, fixed width).
    """
    row = QHBoxLayout()
    row.setSpacing(_SP)

    # ---- Left: Video table card ----
    video_card = NeumorphicCard()
    video_layout = QVBoxLayout(video_card)
    video_layout.setSpacing(_MC)
    video_layout.setContentsMargins(
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
    )

    header = QHBoxLayout()
    header.addWidget(_icon_title("fa5s.film", "Videos"))
    header.addStretch()
    self.video_total_label = WidgetFactory.create_status_label("Total: 0")
    header.addWidget(self.video_total_label)
    self.video_selected_label = WidgetFactory.create_status_label("Selected: 0")
    header.addWidget(self.video_selected_label)
    video_layout.addLayout(header)

    # Filter checkboxes row
    filter_row = QHBoxLayout()
    filter_row.setSpacing(_MC)
    self.filter_scheduled_check = QCheckBox("Scheduled")
    self.filter_scheduled_check.setStyleSheet(
      "background: transparent; border: none;"
    )
    self.filter_published_check = QCheckBox("Published")
    self.filter_published_check.setStyleSheet(
      "background: transparent; border: none;"
    )
    filter_row.addWidget(self.filter_scheduled_check)
    filter_row.addWidget(self.filter_published_check)
    filter_row.addStretch()
    video_layout.addLayout(filter_row)

    self.video_table = WidgetFactory.create_video_table()
    self.video_table.setMinimumHeight(110)
    self.video_table.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    video_layout.addWidget(self.video_table)

    video_card.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    row.addWidget(video_card, 3)

    # ---- Right: Action buttons card ----
    action_card = NeumorphicCard()
    action_layout = QVBoxLayout(action_card)
    action_layout.setSpacing(_SM)
    action_layout.setContentsMargins(
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
    )

    action_layout.addWidget(_icon_title("fa5s.bolt", "Actions"))

    self.start_btn = WidgetFactory.create_button(
      " Execute", btn_class="primary", enabled=False
    )
    self.start_btn.setIcon(qta.icon("fa5s.play-circle", color="#FFFFFF"))
    self.start_btn.setIconSize(QSize(14, 14))
    action_layout.addWidget(self.start_btn)

    self.stop_btn = WidgetFactory.create_button(
      " Stop", btn_class="danger", enabled=False
    )
    self.stop_btn.setIcon(qta.icon("fa5s.stop-circle", color="#FFFFFF"))
    self.stop_btn.setIconSize(QSize(14, 14))
    action_layout.addWidget(self.stop_btn)

    self.pause_btn = WidgetFactory.create_button(" Pause", enabled=False)
    self.pause_btn.setIcon(qta.icon("fa5s.pause-circle", color=_IC))
    self.pause_btn.setIconSize(QSize(14, 14))
    action_layout.addWidget(self.pause_btn)

    # Separator space
    action_layout.addSpacing(_SM)

    self.headless_check = WidgetFactory.create_checkbox(" Headless", checked=True)
    self.headless_check.setIcon(qta.icon("fa5s.eye-slash", color=_IC2))
    action_layout.addWidget(self.headless_check)
    self.retry_check = WidgetFactory.create_checkbox(" Retry", checked=True)
    self.retry_check.setIcon(qta.icon("fa5s.redo-alt", color=_IC2))
    action_layout.addWidget(self.retry_check)

    action_layout.addSpacing(_SM)

    self.export_btn = WidgetFactory.create_button(" Export Report")
    self.export_btn.setIcon(qta.icon("fa5s.file-export", color=_IC))
    self.export_btn.setIconSize(QSize(14, 14))
    action_layout.addWidget(self.export_btn)

    action_layout.addStretch()

    action_card.setFixedWidth(180)
    action_card.setSizePolicy(
      QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
    )
    row.addWidget(action_card, 0)

    self._root.addLayout(row, 1)  # stretch=1 so this row grows

  # ================================================================
  # LOGGER
  # ================================================================

  def _build_logger_section(self) -> None:
    """
    Build the logger card with inset neumorphic log panel.
    """
    card = NeumorphicCard()
    layout = QVBoxLayout(card)
    layout.setSpacing(_MC)
    layout.setContentsMargins(
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
      StyleSheet.SP_CARD, StyleSheet.SP_CARD,
    )

    header_row = QHBoxLayout()
    header_row.addWidget(_icon_title("fa5s.terminal", "Log"))
    header_row.addStretch()
    self.log_clear_button = QPushButton()
    self.log_clear_button.setIcon(qta.icon("fa5s.trash-alt", color=_IC2))
    self.log_clear_button.setIconSize(QSize(14, 14))
    self.log_clear_button.setToolTip("Clear log")
    self.log_clear_button.setFixedSize(26, 26)
    self.log_clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.log_clear_button.setStyleSheet(
      f"QPushButton {{"
      f"  background: transparent; border: none;"
      f"  border-radius: 4px;"
      f"}}"
      f"QPushButton:hover {{"
      f"  background-color: rgba(255,255,255,0.08);"
      f"}}"
    )
    self.log_clear_button.clicked.connect(self._clear_log)
    header_row.addWidget(self.log_clear_button)
    layout.addLayout(header_row)

    self.log_panel = WidgetFactory.create_log_panel(min_height=120)
    self.log_panel.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    layout.addWidget(self.log_panel)

    card.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    self._root.addWidget(card, 1)  # stretch=1

  # ================================================================
  # STATUS ROW
  # ================================================================

  def _build_status_row(self) -> None:
    """
    Build the status bar with progress and counters.
    """
    row = QHBoxLayout()
    row.setSpacing(_SM)

    # Progress icon
    prog_ic = QLabel()
    prog_ic.setPixmap(
      qta.icon("fa5s.tasks", color=_IC2).pixmap(QSize(14, 14))
    )
    prog_ic.setStyleSheet("background: transparent; border: none;")
    row.addWidget(prog_ic)

    self.progress_bar = WidgetFactory.create_progress_bar()
    self.progress_bar.setSizePolicy(
      QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    row.addWidget(self.progress_bar)

    self.progress_label = WidgetFactory.create_status_label("0/0")
    row.addWidget(self.progress_label)

    # Success icon + label
    success_ic = QLabel()
    success_ic.setPixmap(
      qta.icon("fa5s.check-circle", color=StyleSheet.COLORS['success'])
        .pixmap(QSize(14, 14))
    )
    success_ic.setStyleSheet("background: transparent; border: none;")
    row.addWidget(success_ic)
    self.success_label = WidgetFactory.create_status_label("0")
    self.success_label.setStyleSheet(
      f"color: {StyleSheet.COLORS['success']}; font-size: 12px; "
      f"background: transparent; border: none;"
    )
    row.addWidget(self.success_label)

    # Failed icon + label
    fail_ic = QLabel()
    fail_ic.setPixmap(
      qta.icon("fa5s.times-circle", color=StyleSheet.COLORS['error'])
        .pixmap(QSize(14, 14))
    )
    fail_ic.setStyleSheet("background: transparent; border: none;")
    row.addWidget(fail_ic)
    self.failure_label = WidgetFactory.create_status_label("0")
    self.failure_label.setStyleSheet(
      f"color: {StyleSheet.COLORS['error']}; font-size: 12px; "
      f"background: transparent; border: none;"
    )
    row.addWidget(self.failure_label)

    self._root.addLayout(row)

  # ================================================================
  # PUBLIC HELPERS  (called by controller)
  # ================================================================

  def _clear_log(self) -> None:
    """Clear all content from the log panel."""
    self.log_panel.clear()

  def append_log(self, message: str, level: int = 20) -> None:
    """
    Thread-safe log append.

    Emits ``_log_signal`` so that the actual widget update is always
    executed on the main thread, even when called from a worker
    ``QThread``.  Qt's default ``AutoConnection`` queues the call
    when emitter and receiver live in different threads.

    :param message: Formatted log message.
    :type message: str
    :param level: Numeric log level.
    :type level: int
    """
    self._log_signal.emit(message, level)

  def _do_append_log(self, message: str, level: int) -> None:
    """
    Append a colour-coded log message (runs on main thread only).

    Connected to ``_log_signal``; never call directly from outside.

    :param message: Formatted log message.
    :type message: str
    :param level: Numeric log level.
    :type level: int
    """
    color = StyleSheet.log_color(level)
    self.log_panel.append(
      f'<span style="color: {color};">{message}</span>'
    )
    sb = self.log_panel.verticalScrollBar()
    sb.setValue(sb.maximum())

  def update_progress(
    self, current: int, total: int, success: int, failed: int,
  ) -> None:
    """
    Update the status bar.

    :param current: Completed uploads.
    :type current: int
    :param total: Total uploads.
    :type total: int
    :param success: Successful uploads.
    :type success: int
    :param failed: Failed uploads.
    :type failed: int
    """
    pct = int((current / total) * 100) if total > 0 else 0
    self.progress_bar.setValue(pct)
    self.progress_label.setText(f"{current}/{total}")
    self.success_label.setText(f"{success}")
    self.failure_label.setText(f"{failed}")

  def set_upload_running(self, running: bool) -> None:
    """
    Toggle UI between running and idle states.

    :param running: True if upload is in progress.
    :type running: bool
    """
    self.start_btn.setEnabled(not running)
    self.stop_btn.setEnabled(running)
    self.pause_btn.setEnabled(running)
    self.generate_btn.setEnabled(not running)
    self.folder_dropdown.setEnabled(not running)
    self.browse_button.setEnabled(not running)
    self.scan_button.setEnabled(not running)
    self.account_dropdown.setEnabled(not running)

  def show_schedule_warning(self, message: str) -> None:
    """
    Show inline validation warning and red-highlight date fields.

    :param message: Warning text.
    :type message: str
    """
    self.schedule_warning.setText(message)
    self.schedule_warning.show()
    err_border = f"border: 1px solid {StyleSheet.COLORS['border_error']};"
    self.start_date.setStyleSheet(err_border)
    self.end_date.setStyleSheet(err_border)

  def clear_schedule_warning(self) -> None:
    """
    Hide the warning and reset date field styling.
    """
    self.schedule_warning.setText("")
    self.schedule_warning.hide()
    self.start_date.setStyleSheet("")
    self.end_date.setStyleSheet("")

  def show_time_warning(self, message: str) -> None:
    """
    Show inline time validation warning (red text).

    :param message: Warning text.
    :type message: str
    """
    self.time_warning.setText(message)
    self.time_warning.show()

  def clear_time_warning(self) -> None:
    """
    Hide the time validation warning.
    """
    self.time_warning.setText("")
    self.time_warning.hide()

  def set_actions_enabled(self, enabled: bool) -> None:
    """
    Enable/disable primary actions when date range is invalid.

    :param enabled: Whether to enable.
    :type enabled: bool
    """
    self.generate_btn.setEnabled(enabled)
    if not enabled:
      self.start_btn.setEnabled(False)

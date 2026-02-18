from __future__ import annotations

from PyQt6.QtCore import QDate, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDateEdit,
  QDialog,
  QFrame,
  QGraphicsDropShadowEffect,
  QGroupBox,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QProgressBar,
  QPushButton,
  QSizePolicy,
  QSpinBox,
  QTableWidget,
  QTextEdit,
  QVBoxLayout,
  QWidget,
)

from gui.styles import StyleSheet


class NeumorphicCard(QFrame):
  """
  A QFrame styled as a raised neumorphic card with dual drop-shadow.

  Uses ``QGraphicsDropShadowEffect`` for a real soft shadow on platforms
  that support it, plus border/background via QSS for the surface.

  :param parent: Parent widget.
  :type parent: QWidget | None
  """

  def __init__(self, parent: QWidget | None = None) -> None:
    """
    Initialize NeumorphicCard.

    :param parent: Parent widget.
    :type parent: QWidget | None
    """
    super().__init__(parent)
    self.setProperty("class", "card")
    self.setStyleSheet(StyleSheet.card_style())

    # Real drop shadow (dark side — deeper for dark neumorphism)
    shadow = QGraphicsDropShadowEffect(self)
    shadow.setBlurRadius(24)
    shadow.setOffset(6, 6)
    shadow.setColor(QColor(12, 12, 16, 180))  # ~70% opacity near-black
    self.setGraphicsEffect(shadow)


class MarqueeComboBox(QComboBox):
  """QComboBox with auto-scrolling text for long paths.

  The displayed text scrolls horizontally back-and-forth so that full
  paths remain readable within a compact, fixed-width dropdown field.

  :param scroll_speed_ms: Milliseconds between each scroll step.
  :type scroll_speed_ms: int
  :param pause_steps: Number of steps to pause at each end.
  :type pause_steps: int
  :param parent: Parent widget.
  :type parent: QWidget | None
  """

  def __init__(
    self,
    scroll_speed_ms: int = 80,
    pause_steps: int = 15,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setEditable(True)
    self.lineEdit().setReadOnly(True)
    self.setMaxVisibleItems(12)
    # Prevent the combo from expanding to fit long text
    self.setSizeAdjustPolicy(
      QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    self.setMinimumContentsLength(20)

    # Clicking on the read-only line edit should open the popup
    self.lineEdit().installEventFilter(self)

    self._scroll_timer = QTimer(self)
    self._scroll_timer.timeout.connect(self._scroll_step)
    self._scroll_speed = scroll_speed_ms
    self._pause_steps = pause_steps
    self._scroll_pos = 0
    self._scroll_dir = 1  # 1 = forward, -1 = backward
    self._pause_counter = 0

    self.currentIndexChanged.connect(self._on_item_changed)

  def setPlaceholderText(self, text: str) -> None:  # noqa: N802
    """Forward placeholder text to the internal line edit."""
    self.lineEdit().setPlaceholderText(text)

  def eventFilter(self, obj, event) -> bool:  # noqa: N802
    """Open popup when the read-only line edit is clicked."""
    from PyQt6.QtCore import QEvent
    if obj is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
      self.showPopup()
      return True
    return super().eventFilter(obj, event)

  def _on_item_changed(self) -> None:
    """Reset scroll state when the selected item changes."""
    self._scroll_pos = 0
    self._scroll_dir = 1
    self._pause_counter = 0
    le = self.lineEdit()
    le.setCursorPosition(0)
    le.home(False)
    self._start_if_needed()

  def showEvent(self, event) -> None:  # noqa: N802
    """Start scrolling when the widget becomes visible."""
    super().showEvent(event)
    self._start_if_needed()

  def resizeEvent(self, event) -> None:  # noqa: N802
    """Re-evaluate scrolling when the widget is resized."""
    super().resizeEvent(event)
    self._start_if_needed()

  def _start_if_needed(self) -> None:
    """Start the scroll timer only if the text overflows."""
    le = self.lineEdit()
    text_w = le.fontMetrics().horizontalAdvance(le.text())
    if text_w > le.width() and not self._scroll_timer.isActive():
      self._scroll_timer.start(self._scroll_speed)
    elif text_w <= le.width():
      self._scroll_timer.stop()
      le.setCursorPosition(0)
      le.home(False)

  def _scroll_step(self) -> None:
    """Advance cursor position by one step (with pause at each end)."""
    le = self.lineEdit()
    text = le.text()
    if not text:
      self._scroll_timer.stop()
      return

    text_w = le.fontMetrics().horizontalAdvance(text)
    if text_w <= le.width():
      self._scroll_timer.stop()
      le.setCursorPosition(0)
      le.home(False)
      return

    # Pause at each end for readability
    if self._pause_counter > 0:
      self._pause_counter -= 1
      return

    max_pos = len(text)
    self._scroll_pos += self._scroll_dir

    if self._scroll_pos >= max_pos:
      self._scroll_pos = max_pos
      self._scroll_dir = -1
      self._pause_counter = self._pause_steps
    elif self._scroll_pos <= 0:
      self._scroll_pos = 0
      self._scroll_dir = 1
      self._pause_counter = self._pause_steps

    le.setCursorPosition(self._scroll_pos)


class WidgetFactory:
  """
  Factory class for creating styled, consistent GUI widgets.

  All methods are static and return pre-configured PyQt6 widgets
  following the dark-grey neumorphic design.
  """

  # ----------------------------------------------------------------
  # Labels
  # ----------------------------------------------------------------

  @staticmethod
  def create_label(text: str, bold: bool = False, size: int = 13) -> QLabel:
    """
    Create a standard label.

    :param text: Label text.
    :type text: str
    :param bold: Whether to bold the text.
    :type bold: bool
    :param size: Font size in px.
    :type size: int
    :return: Configured QLabel.
    :rtype: QLabel
    """
    label = QLabel(text)
    weight = "600" if bold else "400"
    label.setStyleSheet(
      f"font-size: {size}px; font-weight: {weight}; "
      f"color: {StyleSheet.COLORS['text_primary']}; background: transparent; "
      f"border: none;"
    )
    return label

  @staticmethod
  def create_section_title(text: str) -> QLabel:
    """
    Create a section title label (16px semi-bold).

    :param text: Title text.
    :type text: str
    :return: Configured QLabel.
    :rtype: QLabel
    """
    label = QLabel(text)
    label.setStyleSheet(
      f"font-size: 15px; font-weight: 700; "
      f"color: {StyleSheet.COLORS['text_primary']}; background: transparent; "
      f"border: none; "
      f"padding: 0px 0px 4px 0px;"
    )
    return label

  @staticmethod
  def create_status_label(text: str = "") -> QLabel:
    """
    Create a small status indicator label.

    :param text: Initial text.
    :type text: str
    :return: Configured QLabel.
    :rtype: QLabel
    """
    label = QLabel(text)
    label.setStyleSheet(
      f"font-size: 12px; color: {StyleSheet.COLORS['text_secondary']}; "
      f"background: transparent; border: none;"
    )
    return label

  @staticmethod
  def create_warning_label(text: str = "") -> QLabel:
    """
    Create an inline validation warning label (red text, hidden by default).

    :param text: Initial warning text.
    :type text: str
    :return: Configured QLabel.
    :rtype: QLabel
    """
    label = QLabel(text)
    label.setProperty("class", "warning")
    label.setStyleSheet(
      f"color: {StyleSheet.COLORS['error']}; font-size: 12px; "
      f"font-weight: 500; background: transparent; border: none;"
    )
    label.setWordWrap(True)
    if not text:
      label.hide()
    return label

  # ----------------------------------------------------------------
  # Inputs
  # ----------------------------------------------------------------

  @staticmethod
  def create_dropdown(items: list[str] | None = None) -> QComboBox:
    """
    Create a styled dropdown.

    :param items: Optional initial items.
    :type items: list[str] | None
    :return: Configured QComboBox.
    :rtype: QComboBox
    """
    combo = QComboBox()
    combo.setMaxVisibleItems(12)
    if items:
      combo.addItems(items)
    return combo

  @staticmethod
  def create_hour_dropdown() -> QComboBox:
    """
    Create a scrollable hour dropdown (``00``-``23``).

    :return: QComboBox with 24 zero-padded hour strings.
    :rtype: QComboBox
    """
    combo = QComboBox()
    combo.setMaxVisibleItems(12)
    combo.addItems([f"{h:02d}" for h in range(24)])
    combo.setMinimumWidth(62)
    return combo

  @staticmethod
  def create_minute_dropdown(step: int = 5) -> QComboBox:
    """
    Create a scrollable minute dropdown at the configured step.

    :param step: Minute granularity.
    :type step: int
    :return: QComboBox with valid minute strings.
    :rtype: QComboBox
    """
    combo = QComboBox()
    combo.setMaxVisibleItems(12)
    combo.addItems([f"{m:02d}" for m in range(0, 60, step)])
    combo.setMinimumWidth(62)
    return combo

  @staticmethod
  def create_path_input(placeholder: str = "") -> QLineEdit:
    """
    Create a read-only path input field.

    :param placeholder: Placeholder text.
    :type placeholder: str
    :return: Configured QLineEdit.
    :rtype: QLineEdit
    """
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    line.setReadOnly(True)
    return line

  @staticmethod
  def create_text_input(placeholder: str = "") -> QLineEdit:
    """
    Create an editable text input field.

    :param placeholder: Placeholder text.
    :type placeholder: str
    :return: Configured QLineEdit.
    :rtype: QLineEdit
    """
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    return line

  @staticmethod
  def create_spin_input(
    minimum: int = 0,
    maximum: int = 999,
    value: int = 0,
    suffix: str = "",
  ) -> QSpinBox:
    """
    Create a styled numeric spin box.

    :param minimum: Min value.
    :type minimum: int
    :param maximum: Max value.
    :type maximum: int
    :param value: Initial value.
    :type value: int
    :param suffix: Suffix text.
    :type suffix: str
    :return: Configured QSpinBox.
    :rtype: QSpinBox
    """
    spin = QSpinBox()
    spin.setMinimum(minimum)
    spin.setMaximum(maximum)
    spin.setValue(value)
    if suffix:
      spin.setSuffix(suffix)
    return spin

  @staticmethod
  def create_date_input(default_date: QDate | None = None) -> QDateEdit:
    """
    Create a styled date picker.

    :param default_date: Initial date.
    :type default_date: QDate | None
    :return: Configured QDateEdit.
    :rtype: QDateEdit
    """
    date_edit = QDateEdit()
    date_edit.setCalendarPopup(True)
    date_edit.setDisplayFormat("yyyy-MM-dd")
    date_edit.setDate(default_date or QDate.currentDate())
    return date_edit

  @staticmethod
  def create_checkbox(text: str, checked: bool = False) -> QCheckBox:
    """
    Create a styled checkbox.

    :param text: Label text.
    :type text: str
    :param checked: Initial state.
    :type checked: bool
    :return: Configured QCheckBox.
    :rtype: QCheckBox
    """
    cb = QCheckBox(text)
    cb.setChecked(checked)
    return cb

  # ----------------------------------------------------------------
  # Action buttons
  # ----------------------------------------------------------------

  @staticmethod
  def create_button(
    text: str,
    btn_class: str = "",
    enabled: bool = True,
  ) -> QPushButton:
    """
    Create a styled button.

    :param text: Button label.
    :type text: str
    :param btn_class: ``'primary'``, ``'danger'``, or ``''``.
    :type btn_class: str
    :param enabled: Initial enabled state.
    :type enabled: bool
    :return: Configured QPushButton.
    :rtype: QPushButton
    """
    btn = QPushButton(text)
    if btn_class:
      btn.setProperty("class", btn_class)
    btn.setEnabled(enabled)
    return btn

  @staticmethod
  def create_icon_button(icon_text: str) -> QPushButton:
    """
    Create a small square icon button (e.g. ``+``).

    :param icon_text: Single character to display.
    :type icon_text: str
    :return: Configured QPushButton.
    :rtype: QPushButton
    """
    btn = QPushButton(icon_text)
    btn.setFixedSize(36, 36)
    c = StyleSheet.COLORS
    btn.setStyleSheet(
      f"QPushButton {{"
      f"  background-color: {c['primary']};"
      f"  color: {c['text_on_primary']};"
      f"  border: none;"
      f"  border-radius: 8px;"
      f"  font-size: 18px;"
      f"  font-weight: 700;"
      f"  padding: 0px;"
      f"}}"
      f"QPushButton:hover {{"
      f"  background-color: {c['primary_hover']};"
      f"}}"
      f"QPushButton:pressed {{"
      f"  background-color: {c['primary_pressed']};"
      f"}}"
    )
    return btn

  # ----------------------------------------------------------------
  # Panels
  # ----------------------------------------------------------------

  @staticmethod
  def create_log_panel(min_height: int = 140) -> QTextEdit:
    """
    Create a read-only log panel.

    :param min_height: Minimum height.
    :type min_height: int
    :return: Configured QTextEdit.
    :rtype: QTextEdit
    """
    te = QTextEdit()
    te.setReadOnly(True)
    te.setMinimumHeight(min_height)
    return te

  @staticmethod
  def create_progress_bar() -> QProgressBar:
    """
    Create a styled progress bar.

    :return: Configured QProgressBar.
    :rtype: QProgressBar
    """
    pb = QProgressBar()
    pb.setRange(0, 100)
    pb.setValue(0)
    pb.setTextVisible(True)
    return pb

  @staticmethod
  def create_video_table() -> QTableWidget:
    """
    Create a styled video table with 5 columns.

    Columns: Select, Filename, Size, Schedule Time, Status.

    :return: Configured QTableWidget.
    :rtype: QTableWidget
    """
    table = QTableWidget()
    table.setColumnCount(5)
    table.setHorizontalHeaderLabels([
      "Select", "Filename", "Size", "Schedule Time", "Status",
    ])
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setColumnWidth(0, 50)
    table.setColumnWidth(1, 250)
    table.setColumnWidth(2, 80)
    table.setColumnWidth(3, 250)
    return table


class AddAccountDialog(QDialog):
  """
  Modal dialog for adding a new account cookie.

  Contains a username input, a textarea for pasting cookie JSON,
  a validation error label, and Cancel / Save buttons.

  :param parent: Parent widget.
  :type parent: QWidget | None
  """

  def __init__(self, parent: QWidget | None = None) -> None:
    """
    Initialize AddAccountDialog.

    :param parent: Parent widget.
    :type parent: QWidget | None
    """
    super().__init__(parent)
    self.setWindowTitle("Add Account Cookie")
    self.setMinimumSize(480, 420)
    self.setModal(True)

    c = StyleSheet.COLORS
    self.setStyleSheet(
      f"QDialog {{"
      f"  background-color: {c['bg_card']};"
      f"  color: {c['text_primary']};"
      f"}}"
    )

    layout = QVBoxLayout(self)
    layout.setSpacing(12)
    layout.setContentsMargins(24, 24, 24, 24)

    # Title
    title = QLabel("Add Account")
    title.setStyleSheet(
      f"font-size: 16px; font-weight: 700; "
      f"color: {c['text_primary']}; background: transparent; border: none;"
    )
    layout.addWidget(title)

    # Username input
    username_label = QLabel("Username")
    username_label.setStyleSheet(
      f"font-size: 13px; color: {c['text_secondary']}; "
      f"background: transparent; border: none;"
    )
    layout.addWidget(username_label)

    self.username_input = QLineEdit()
    self.username_input.setPlaceholderText("e.g. myaccount.name")
    layout.addWidget(self.username_input)

    # Cookie textarea
    cookie_label = QLabel("Cookie JSON")
    cookie_label.setStyleSheet(
      f"font-size: 13px; color: {c['text_secondary']}; "
      f"background: transparent; border: none;"
    )
    layout.addWidget(cookie_label)

    self.cookie_input = QTextEdit()
    self.cookie_input.setPlaceholderText(
      'Paste cookie JSON array here...\n'
      '[{"name": "...", "value": "...", "domain": "...", "path": "/"}, ...]'
    )
    self.cookie_input.setMinimumHeight(180)
    layout.addWidget(self.cookie_input)

    # Validation error label
    self.error_label = QLabel("")
    self.error_label.setStyleSheet(
      f"color: {c['error']}; font-size: 12px; font-weight: 500; "
      f"background: transparent; border: none;"
    )
    self.error_label.setWordWrap(True)
    self.error_label.hide()
    layout.addWidget(self.error_label)

    # Buttons
    btn_row = QHBoxLayout()
    btn_row.setSpacing(12)
    btn_row.addStretch()

    self.cancel_btn = QPushButton("Cancel")
    self.cancel_btn.setMinimumWidth(90)
    self.cancel_btn.clicked.connect(self.reject)
    btn_row.addWidget(self.cancel_btn)

    self.save_btn = QPushButton("Save")
    self.save_btn.setProperty("class", "primary")
    self.save_btn.setMinimumWidth(90)
    btn_row.addWidget(self.save_btn)

    layout.addLayout(btn_row)

  def show_error(self, message: str) -> None:
    """
    Show a validation error message.

    :param message: Error text.
    :type message: str
    """
    self.error_label.setText(message)
    self.error_label.show()

  def clear_error(self) -> None:
    """Hide the validation error."""
    self.error_label.setText("")
    self.error_label.hide()

  def get_username(self) -> str:
    """
    Return the trimmed username text.

    :rtype: str
    """
    return self.username_input.text().strip()

  def get_cookie_text(self) -> str:
    """
    Return the raw cookie textarea content.

    :rtype: str
    """
    return self.cookie_input.toPlainText().strip()

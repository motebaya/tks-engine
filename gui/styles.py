from __future__ import annotations


class StyleSheet:
  """
  Dark-grey Neumorphism (Soft UI) stylesheet for the TikTok Uploader.

  Uses a neutral dark-grey palette with dual soft shadows (lighter grey
  highlight, darker grey shade) to produce raised, inset, and flat
  interaction states.  No purple, no black, no saturated accent shadows.

  Primary action colour: blue ``#1E66FF`` (configurable via config).
  """

  # ----------------------------------------------------------------
  # Colour tokens
  # ----------------------------------------------------------------

  COLORS: dict[str, str] = {
    # Surfaces — dark grey neumorphism
    "bg_base": "#2D2D35",
    "bg_card": "#33333C",
    "bg_inset": "#26262E",
    "bg_input": "#2A2A32",
    "bg_hover": "#3A3A44",

    # Neumorphic shadows (CSS rgba)
    "shadow_dark": "rgba(18, 18, 22, 0.6)",
    "shadow_light": "rgba(60, 60, 70, 0.5)",

    # Primary (blue)
    "primary": "#1E66FF",
    "primary_hover": "#4080FF",
    "primary_pressed": "#1450CC",
    "primary_disabled": "#3A4F7A",

    # Semantic
    "success": "#2ECC71",
    "warning": "#E67E22",
    "error": "#E74C3C",
    "info": "#3498DB",

    # Text — light text on dark surfaces
    "text_primary": "#E0E0E8",
    "text_secondary": "#9A9AA8",
    "text_disabled": "#5C5C6A",
    "text_on_primary": "#FFFFFF",

    # Borders
    "border_subtle": "#3E3E48",
    "border_focus": "#1E66FF",
    "border_error": "#E74C3C",

    # Scrollbar
    "scrollbar_bg": "#2D2D35",
    "scrollbar_handle": "#4A4A55",
    "scrollbar_hover": "#5A5A66",
  }

  # Spacing scale (px)
  SP_MICRO: int = 8
  SP_SMALL: int = 12
  SP_STD: int = 16
  SP_CARD: int = 24
  SP_SECTION: int = 32

  # Radii
  RADIUS_CARD: str = "18px"
  RADIUS_BTN: str = "10px"
  RADIUS_INPUT: str = "10px"
  RADIUS_SM: str = "8px"

  # ----------------------------------------------------------------
  # Primary colour override
  # ----------------------------------------------------------------

  @classmethod
  def apply_primary_color(cls, color: str) -> None:
    """
    Override the primary colour from ``config.json``.

    :param color: Hex colour string (e.g. ``'#1E66FF'``).
    :type color: str
    """
    cls.COLORS["primary"] = color
    cls.COLORS["primary_hover"] = cls._lighten(color, 0.20)
    cls.COLORS["primary_pressed"] = cls._darken(color, 0.18)
    cls.COLORS["primary_disabled"] = cls._lighten(color, 0.50)
    cls.COLORS["border_focus"] = color

  # ----------------------------------------------------------------
  # Global QSS
  # ----------------------------------------------------------------

  @classmethod
  def global_stylesheet(cls) -> str:
    """
    Return the complete QSS stylesheet for the application.

    :return: Full QSS string.
    :rtype: str
    """
    c = cls.COLORS
    rc = cls.RADIUS_CARD
    rb = cls.RADIUS_BTN
    ri = cls.RADIUS_INPUT
    rs = cls.RADIUS_SM

    return f"""
      /* ======== WINDOW ======== */
      QMainWindow {{
        background-color: {c["bg_base"]};
      }}
      QWidget {{
        background-color: transparent;
        color: {c["text_primary"]};
        font-family: "Inter", "Segoe UI", "Roboto", sans-serif;
        font-size: 13px;
      }}

      /* ======== LABELS ======== */
      QLabel {{
        color: {c["text_primary"]};
        background: transparent;
        padding: 0px;
      }}

      /* ======== NEUMORPHIC CARD (QFrame class=card) ======== */
      QFrame[class="card"] {{
        background-color: {c["bg_card"]};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: {rc};
      }}

      /* ======== GROUP BOX ======== */
      QGroupBox {{
        background-color: {c["bg_card"]};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: {rc};
        margin-top: 6px;
        padding: 18px 16px 14px 16px;
        font-weight: 600;
        font-size: 13px;
        color: {c["text_secondary"]};
      }}
      QGroupBox::title {{
        subcontrol-origin: margin;
        left: 18px;
        padding: 0px 8px;
        color: {c["text_secondary"]};
      }}

      /* ======== BUTTONS — grey raised ======== */
      QPushButton {{
        background-color: {c["bg_card"]};
        color: {c["text_primary"]};
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: {rb};
        padding: 8px 20px;
        font-weight: 500;
        min-height: 36px;
        font-size: 13px;
      }}
      QPushButton:hover {{
        background-color: {c["bg_hover"]};
        border: 1px solid rgba(255, 255, 255, 0.12);
      }}
      QPushButton:pressed {{
        background-color: {c["bg_inset"]};
        border: 1px solid {c["border_subtle"]};
      }}
      QPushButton:disabled {{
        background-color: {c["bg_base"]};
        color: {c["text_disabled"]};
        border: 1px solid transparent;
      }}

      /* PRIMARY blue */
      QPushButton[class="primary"] {{
        background-color: {c["primary"]};
        color: {c["text_on_primary"]};
        border: none;
        font-weight: 700;
      }}
      QPushButton[class="primary"]:hover {{
        background-color: {c["primary_hover"]};
      }}
      QPushButton[class="primary"]:pressed {{
        background-color: {c["primary_pressed"]};
      }}
      QPushButton[class="primary"]:disabled {{
        background-color: {c["primary_disabled"]};
        color: rgba(255,255,255,0.35);
      }}

      /* DANGER red */
      QPushButton[class="danger"] {{
        background-color: {c["error"]};
        color: {c["text_on_primary"]};
        border: none;
        font-weight: 600;
      }}
      QPushButton[class="danger"]:hover {{
        background-color: #FF6B6B;
      }}
      QPushButton[class="danger"]:pressed {{
        background-color: #C0392B;
      }}
      QPushButton[class="danger"]:disabled {{
        background-color: #5C3030;
        color: rgba(255,255,255,0.35);
      }}

      /* ======== INPUTS — inset ======== */
      QLineEdit, QSpinBox, QDateEdit, QTimeEdit {{
        background-color: {c["bg_inset"]};
        color: {c["text_primary"]};
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: {ri};
        padding: 6px 12px;
        min-height: 30px;
        selection-background-color: {c["primary"]};
        selection-color: {c["text_on_primary"]};
        font-size: 13px;
      }}
      QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {{
        border: 1px solid {c["border_focus"]};
      }}
      QLineEdit:disabled {{
        background-color: {c["bg_base"]};
        color: {c["text_disabled"]};
      }}
      QLineEdit[state="error"] {{
        border: 1px solid {c["border_error"]};
      }}

      /* ======== COMBOBOX — raised ======== */
      QComboBox {{
        background-color: {c["bg_card"]};
        color: {c["text_primary"]};
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: {ri};
        padding: 6px 12px;
        min-height: 30px;
        font-size: 13px;
      }}
      QComboBox:hover {{
        background-color: {c["bg_hover"]};
        border: 1px solid rgba(255,255,255,0.12);
      }}
      QComboBox::drop-down {{
        border: none;
        width: 28px;
      }}
      QComboBox QAbstractItemView {{
        background-color: {c["bg_card"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border_subtle"]};
        border-radius: 6px;
        selection-background-color: {c["primary"]};
        selection-color: {c["text_on_primary"]};
        outline: none;
        padding: 4px;
      }}

      /* ======== CHECKBOX ======== */
      QCheckBox {{
        color: {c["text_primary"]};
        spacing: 8px;
        background: transparent;
        font-size: 13px;
      }}
      QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        border: 1px solid {c["border_subtle"]};
        border-radius: 6px;
        background-color: {c["bg_inset"]};
      }}
      QCheckBox::indicator:checked {{
        background-color: {c["primary"]};
        border-color: {c["primary"]};
      }}
      QCheckBox::indicator:hover {{
        border-color: {c["primary"]};
      }}

      /* ======== TABLE ======== */
      QTableWidget {{
        background-color: {c["bg_card"]};
        color: {c["text_primary"]};
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: {ri};
        gridline-color: {c["border_subtle"]};
        selection-background-color: {c["primary"]};
        selection-color: {c["text_on_primary"]};
        font-size: 13px;
      }}
      QTableWidget::item {{
        padding: 5px 8px;
      }}
      QTableWidget::item:hover {{
        background-color: rgba(30, 102, 255, 0.12);
      }}
      QHeaderView::section {{
        background-color: {c["bg_base"]};
        color: {c["text_secondary"]};
        border: none;
        border-bottom: 1px solid {c["border_subtle"]};
        padding: 6px 10px;
        font-weight: 600;
        font-size: 12px;
      }}

      /* ======== TEXTEDIT (logger) — inset darker ======== */
      QTextEdit {{
        background-color: {c["bg_inset"]};
        color: {c["text_primary"]};
        border: 1px solid rgba(255,255,255,0.04);
        border-radius: {ri};
        font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
        font-size: 12px;
        padding: 8px;
        selection-background-color: {c["primary"]};
      }}

      /* ======== PROGRESSBAR ======== */
      QProgressBar {{
        background-color: {c["bg_inset"]};
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: {rs};
        text-align: center;
        color: {c["text_primary"]};
        min-height: 22px;
        font-weight: 600;
        font-size: 12px;
      }}
      QProgressBar::chunk {{
        background-color: {c["primary"]};
        border-radius: 7px;
      }}

      /* ======== SCROLLBARS ======== */
      QScrollBar:vertical {{
        background-color: {c["scrollbar_bg"]};
        width: 10px;
        border: none;
        border-radius: 5px;
      }}
      QScrollBar::handle:vertical {{
        background-color: {c["scrollbar_handle"]};
        border-radius: 5px;
        min-height: 30px;
      }}
      QScrollBar::handle:vertical:hover {{
        background-color: {c["scrollbar_hover"]};
      }}
      QScrollBar::add-line:vertical,
      QScrollBar::sub-line:vertical {{
        height: 0px;
      }}
      QScrollBar:horizontal {{
        background-color: {c["scrollbar_bg"]};
        height: 10px;
        border: none;
        border-radius: 5px;
      }}
      QScrollBar::handle:horizontal {{
        background-color: {c["scrollbar_handle"]};
        border-radius: 5px;
        min-width: 30px;
      }}
      QScrollBar::handle:horizontal:hover {{
        background-color: {c["scrollbar_hover"]};
      }}
      QScrollBar::add-line:horizontal,
      QScrollBar::sub-line:horizontal {{
        width: 0px;
      }}

      /* ======== WARNING LABEL ======== */
      QLabel[class="warning"] {{
        color: {c["error"]};
        font-size: 12px;
        font-weight: 500;
        padding: 2px 4px;
        background: transparent;
      }}
    """

  # ----------------------------------------------------------------
  # Log colour
  # ----------------------------------------------------------------

  @classmethod
  def log_color(cls, level: int) -> str:
    """
    Return a CSS colour for a given log level.

    :param level: Numeric log level.
    :type level: int
    :return: Hex colour string.
    :rtype: str
    """
    return {
      10: cls.COLORS["text_secondary"],
      20: cls.COLORS["text_primary"],
      25: cls.COLORS["success"],
      30: cls.COLORS["warning"],
      40: cls.COLORS["error"],
    }.get(level, cls.COLORS["text_primary"])

  # ----------------------------------------------------------------
  # Card helpers for QGraphicsDropShadowEffect usage in code
  # ----------------------------------------------------------------

  @classmethod
  def card_style(cls) -> str:
    """
    Inline QSS for a raised neumorphic card.

    :return: Inline QSS.
    :rtype: str
    """
    c = cls.COLORS
    return (
      f"background-color: {c['bg_card']};"
      f"border: 1px solid rgba(255,255,255,0.06);"
      f"border-radius: {cls.RADIUS_CARD};"
    )

  @classmethod
  def card_inset_style(cls) -> str:
    """
    Inline QSS for an inset (recessed) card.

    :return: Inline QSS.
    :rtype: str
    """
    c = cls.COLORS
    return (
      f"background-color: {c['bg_inset']};"
      f"border: 1px solid rgba(255,255,255,0.04);"
      f"border-radius: {cls.RADIUS_CARD};"
    )

  # ----------------------------------------------------------------
  # Colour math
  # ----------------------------------------------------------------

  @staticmethod
  def _lighten(hex_color: str, factor: float) -> str:
    """
    Lighten a hex colour.

    :param hex_color: Input hex.
    :type hex_color: str
    :param factor: 0-1 factor.
    :type factor: float
    :return: Lightened hex.
    :rtype: str
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"

  @staticmethod
  def _darken(hex_color: str, factor: float) -> str:
    """
    Darken a hex colour.

    :param hex_color: Input hex.
    :type hex_color: str
    :param factor: 0-1 factor.
    :type factor: float
    :return: Darkened hex.
    :rtype: str
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, int(r * (1 - factor)))
    g = max(0, int(g * (1 - factor)))
    b = max(0, int(b * (1 - factor)))
    return f"#{r:02x}{g:02x}{b:02x}"

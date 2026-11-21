import os
from typing import Dict

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

# ------------------------------------------------------------------
# 主题配色表
#
# 供 QSS 管不到的部分取色使用，目前有三类：
#   1. 自绘控件（Window 的圆角窗口、CaptionButton 的图标）——用 QPainter 画的；
#   2. 图形效果（QGraphicsDropShadowEffect 的投影色）——不在 QSS 的能力范围内；
#   3. 占位文字——QSS 的 ::placeholder 伪元素在 Qt 里根本不生效。
#
# 每新增一个主题（styles/ 下的 xxx_theme.qss），就在这里加一份同名配色，
# 否则该主题下这些部分会回落到 light 的配色。
# ------------------------------------------------------------------
THEME_COLORS: Dict[str, Dict[str, str]] = {
    "light": {
        "window_bg": "#f5f7fa",  # 窗口内容区底色
        "window_border": "#d0d7de",  # 窗口描边
        "caption_hover": "#d5d8dd",  # 标题栏按钮悬停底
        "caption_pressed": "#bdc3c7",  # 标题栏按钮按下底
        "caption_close_hover": "#e74c3c",  # 关闭按钮悬停底
        "caption_close_pressed": "#c0392b",  # 关闭按钮按下底
        "caption_fg": "#2c3e50",  # 图标颜色
        "caption_fg_active": "#ffffff",  # 关闭按钮激活时的图标颜色
        "placeholder": "#a0b0c0",  # 占位文字（QSS 的 ::placeholder 在 Qt 里无效）
        "shadow": "#a0a0a4",  # 投影色，等于 Qt.gray（注意 Qt.gray 是 #a0a0a4，
        #   #808080 是 Qt.darkGray，别搞混）
        # ---- SlideSwitch（滑动开关）自绘配色 ----
        "switch_on": "#4a90d9",  # 开启态轨道底色（对齐主按钮的蓝色系）
        "switch_off": "#bdc3c7",  # 关闭态轨道底色
        "switch_knob": "#ffffff",  # 手柄圆点颜色
        "text": "#000000",  # 自绘文字色（对齐 QLabel 正文）
        "text_disabled": "#a0a0a0",  # 禁用文字色
    },
    "dark": {
        # 中性石墨（Neutral Graphite）色板，与 dark_theme.qss 顶部的海拔梯度一一对应：
        #   L0 #18181a / L1 #1f1f24 / L2 #26262b / L3 #2b2b31
        #   L4 #33333a / L5 #3d3d45 / L6 #484852
        # window_bg 必须对齐 QWidget#contentWidget，否则窗口四角会露出色差。
        "window_bg": "#18181a",  # L0，对齐 contentWidget 底色
        "window_border": "#43434c",  # 对齐常规描边
        "caption_hover": "#3d3d45",  # L5
        "caption_pressed": "#484852",  # L6
        "caption_close_hover": "#e0665c",  # danger
        "caption_close_pressed": "#bf4d45",  # danger-pressed
        "caption_fg": "#e8e8ec",  # 图标颜色，对齐 titleLabel 文字色
        "caption_fg_active": "#ffffff",  # 关闭按钮激活时的图标颜色
        "placeholder": "#a2a2ab",  # 占位文字，对齐 text-secondary
        "shadow": "#000000",  # 投影色。深色下的投影要压得比所在面更暗才成立，
        #   用纯黑；浅色下用 Qt.gray。
        # ---- SlideSwitch（滑动开关）自绘配色 ----
        "switch_on": "#5aa2e8",  # 开启态轨道底色，深色下稍微提亮的主蓝
        "switch_off": "#484852",  # L6，关闭态轨道底色
        "switch_knob": "#e8e8ec",  # 手柄圆点颜色
        "text": "#e8e8ec",  # 自绘文字色，对齐正文
        "text_disabled": "#6b6b78",  # 禁用文字色
    },
}

_current_theme: str = "light"


def get_color(key: str) -> str:
    """
    获取当前主题下某个颜色的十六进制值。

    供自绘控件使用——QSS 对 paintEvent 里画出来的内容无效，
    所以 Window 和 CaptionButton 的颜色只能从这里取。

    Args:
        key(str): 颜色键名，如 "window_bg"。

    Returns:
        颜色的十六进制字符串，如 "#f5f7fa"。
        当前主题没登记该键时会回落到 light 主题。
    """
    table = THEME_COLORS.get(_current_theme, THEME_COLORS["light"])
    return table.get(key, THEME_COLORS["light"].get(key, "#000000"))


def current_theme() -> str:
    """获取当前主题名（如 "light"）。"""
    return _current_theme


def apply_themed_shadow(
    widget: QWidget, blur_radius: int = 8, offset_y: int = 1
) -> None:
    """
    给控件挂一个会随主题变色的投影。

    QGraphicsDropShadowEffect 的颜色不由 QSS 控制，改主题时它不会自己变，
    所以统一走这个入口：颜色从 THEME_COLORS 里取，并给控件打上 _themed_shadow
    标记，apply_theme() 切主题时会照着这个标记把新颜色写回去。

    Args:
        widget(QWidget): 要加投影的控件。
        blur_radius(int): 模糊半径，默认 8。
        offset_y(int): 垂直偏移量，默认 1（略微下沉，模拟"浮起"）。
    """
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur_radius)
    shadow.setOffset(0, offset_y)
    shadow.setColor(QColor(get_color("shadow")))
    widget.setGraphicsEffect(shadow)
    widget._themed_shadow = True


def apply_theme(app: QApplication, theme_name: str = "light") -> bool:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    styles_dir = os.path.join(current_dir, "..", "styles")
    theme_file = os.path.join(styles_dir, f"{theme_name}_theme.qss")
    try:
        with open(theme_file, encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print(f"警告：未找到主题文件 {theme_file}")
        return False

    global _current_theme
    _current_theme = theme_name

    # 占位文字的颜色：Qt 的 QSS 不支持 ::placeholder 伪元素（写了也不生效），
    # 只能通过调色板的 PlaceholderText 角色来改。这里只覆盖这一个角色，
    # 其余角色保持 Qt 默认值不动。
    palette = app.palette()
    palette.setColor(
        QPalette.ColorRole.PlaceholderText, QColor(get_color("placeholder"))
    )
    app.setPalette(palette)

    # 自绘控件（Window / CaptionButton）不走 QSS，切主题后必须手动触发重绘；
    # 投影色同理，一并把新色写回带 _themed_shadow 标记的控件。
    for widget in app.allWidgets():
        effect = widget.graphicsEffect()
        if getattr(widget, "_themed_shadow", False) and isinstance(
            effect, QGraphicsDropShadowEffect
        ):
            effect.setColor(QColor(get_color("shadow")))
        widget.update()

    return True

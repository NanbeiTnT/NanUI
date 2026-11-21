from typing import Optional

from NanUI.utils import get_font
from NanUI.utils.theme_manager import get_color

from PySide6.QtCore import (
    QAbstractAnimation,
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import QToolButton, QWidget


class SlideSwitch(QToolButton):
    """
    滑动开关控件（类似手机上的 Toggle Switch）。

    继承自 QToolButton。轨道与手柄由 paintEvent 自绘，颜色取自
    theme_manager 的 THEME_COLORS（switch_on / switch_off / switch_knob 等键），
    切换主题时自动变色；点击后手柄位置带滑动动画。

    Args:
        parent (QWidget, optional): 父控件对象。默认为 None。
        checked (bool): 初始是否为开启状态。默认为 False。
        text (str): 开关右侧显示的文字。默认为空字符串。
        font (str, optional): 字体族名称。默认为 None，即使用全局默认字体（微软雅黑）。
        font_size (int): 字体大小（磅值）。默认为 12。
        track_width (int): 轨道宽度（像素）。默认为 44。
        track_height (int): 轨道高度（像素）。默认为 22。

    Signals:
        toggled(bool): 开关状态改变时发射，参数为新的选中状态。
    """

    toggled = Signal(bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        checked: bool = False,
        text: str = "",
        font: Optional[str] = None,
        font_size: int = 12,
        track_width: int = 44,
        track_height: int = 22,
    ) -> None:
        super().__init__(parent)

        # 屏蔽 QToolButton 内建的 toggled 信号（它由 C++ checkStateChanged 直接
        # 发射，Python 侧无法拦截）：把内部连接全部重定向到空槽，对外只保留
        # 下面重新声明的、走 setChecked() 单一入口的 toggled(bool)。
        try:
            for receiver in self.receivers(self.signalToggled):
                self.disconnect(receiver)
        except (RuntimeError, TypeError):
            pass
        self.toggled.connect(lambda _=None: None)

        self._track_width = track_width
        self._track_height = track_height
        self._handle_ratio = 0.0 if not checked else 1.0
        self._checked_state = checked

        self.setCheckable(True)
        # 接管 QToolButton 的 toggle()：鼠标点击内部走的是 toggle()，直接翻
        # checkState 并发射内建 toggled。统一重定向到 setChecked()，保证状态、
        # 动画与我们自定义的 toggled 信号只有一条路径。
        self.setText(text)
        self.setFont(get_font(size=font_size, family=font))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

        # 手柄滑动动画（目标值是当前 ratio，起止点在每次启动时动态计算）
        self._anim = QPropertyAnimation(self, b"handleRatio", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self.setMinimumSize(self.sizeHint())

    # ---------- 内部逻辑 ----------

    def toggle(self) -> None:
        """接管 QToolButton.toggle()：统一走 setChecked()（见 __init__ 注释）。"""
        self.setChecked(not self._checked_state)

    def _on_clicked(self) -> None:
        """鼠标点击：把新状态交回 setChecked() 统一处理。"""
        self.setChecked(not self.isChecked())

    # ---------- 公开接口 ----------

    def isChecked(self) -> bool:
        """返回开关是否处于开启状态。"""
        return self._checked_state

    def setChecked(self, checked: bool) -> None:
        """
        设置开关的选中状态。

        与状态真正发生变化时才发射 toggled 信号并启动手柄滑动动画；
        传入与当前相同的值时无副作用。

        Args:
            checked(bool): True 为开启，False 为关闭。
        """
        if checked == self._checked_state:
            return
        self._checked_state = checked
        self.setDown(False)  # 清掉 QToolButton 内部的按下态，防止绘制残留
        target = 1.0 if checked else 0.0
        self._anim.stop()
        self._anim.setStartValue(self._handle_ratio)
        self._anim.setEndValue(target)
        self._anim.setDirection(
            QAbstractAnimation.Direction.Forward
            if target >= self._handle_ratio
            else QAbstractAnimation.Direction.Backward
        )
        # setDirection(Backward) 会把 currentTime 翻转到末尾，这里复位到起点，
        # 保证动画从 startValue 开始播。
        self._anim.setCurrentTime(0)
        self._anim.start()
        self.toggled.emit(checked)
        self.update()

    # ---------- 手柄动画属性（Q_PROPERTY handleRatio） ----------

    def _get_handle_ratio(self) -> float:
        return self._handle_ratio

    def _set_handle_ratio(self, value: float) -> None:
        self._handle_ratio = max(0.0, min(1.0, float(value)))
        self.update()

    handleRatio = Property(float, _get_handle_ratio, _set_handle_ratio)

    # ---------- 尺寸与绘制 ----------

    def sizeHint(self) -> QSize:
        """轨道 + 间距 + 文字（若有）的推荐尺寸。"""
        width = self._track_width
        height = max(self._track_height, self.fontMetrics().height())
        if self.text():
            spacing = 6
            width += spacing + self.fontMetrics().horizontalAdvance(self.text())
            height = max(height, self.fontMetrics().height())
        return QSize(width + 4, height + 4)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        # 窗口缩放后动画目标不变，只需重绘
        self.update()

    def _track_rect(self) -> QRect:
        """计算轨道矩形：垂直居中，靠左放置。"""
        y = (self.height() - self._track_height) // 2
        return QRect(2, y, self._track_width, self._track_height)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = self._track_rect()
        radius = track.height() / 2

        # --- 轨道底色：开=主题强调色，关=中性色（均随主题切换） ---
        if self.isChecked():
            track_key = "switch_on" if self.isEnabled() else "text_disabled"
        else:
            track_key = "switch_off" if self.isEnabled() else "caption_hover"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(get_color(track_key)))
        painter.drawRoundedRect(QRect(track), radius, radius)

        # --- 手柄：白色圆点，位置由 handleRatio 插值 ---
        inset = 2
        knob_d = track.height() - inset * 2
        x_left = track.left() + inset
        x_right = track.right() - inset - knob_d
        knob_x = int(x_left + (x_right - x_left) * self._handle_ratio)
        knob = QRect(knob_x, track.top() + inset, knob_d, knob_d)
        painter.setBrush(QColor(get_color("switch_knob")))
        painter.drawEllipse(knob)

        # --- 文字 ---
        if self.text():
            painter.setPen(
                QColor(get_color("text"))
                if self.isEnabled()
                else QColor(get_color("text_disabled"))
            )
            text_rect = QRect(
                track.right() + 8, 0, self.width() - track.right() - 10, self.height()
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, self.text())

        painter.end()

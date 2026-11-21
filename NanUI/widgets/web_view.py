"""
注：本文件部分代码由 AI 辅助开发。
"""

import os
from typing import Any, Optional, Union

from NanUI.utils.theme_manager import get_color

from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import (
        QWebEngineNavigationRequest,
        QWebEngineScript,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_AVAILABLE = True
except ImportError:  # 没装 WebEngine/WebChannel 组件时优雅降级（见类文档）
    QWebEngineNavigationRequest = None  # type: ignore[assignment,misc]
    WEBENGINE_AVAILABLE = False


WEBENGINE_HINT = (
    "WebView 需要 PySide6 的 WebEngine 组件，"
    '请运行: pip install "PySide6-Addons>=6.5"'
)

# qwebchannel.js 注入策略：PySide6 的 wheel 并不打包官方 qwebchannel.js，
# 而完整协议（bootstrap/invoke/property 包装）无法用几十行 JS 可靠复刻，
# 因此这里只做两件事：
#   1. 把 transport 挂到 window.NanUIChannel 上，供页面自行引入官方
#      qwebchannel.js 使用；
#   2. 提供零依赖的 NanUI.postMessage(text) 辅助函数——底层直接走
#      qt.webChannelTransport 的 invoke 帧调用桥对象的 send 槽，
#      Python 侧从 messageReceived 信号收到消息。
_QWEBCHANNEL_INJECT_JS = """
(function () {
    if (window.NanUI) return;
    var t = (typeof qt !== "undefined") ? qt.webChannelTransport : null;
    window.NanUI = {};
    window.NanUI.transport = t || null;
    window.NanUI.postMessage = function (m) {
        if (!t) return;
        t.send(JSON.stringify({
            type: "invoke",
            objectName: "nanui",
            methodName: "send",
            args: [String(m)]
        }));
    };
})();
"""


def _load_qwebchannel_source() -> str:
    """返回注入页面的桥接脚本；若系统里恰好有 Qt 官方 qwebchannel.js 则一并附带。"""
    import PySide6

    base = os.path.dirname(os.path.abspath(PySide6.__file__))
    for dirpath, _dirnames, filenames in os.walk(base):
        if "qwebchannel.js" in filenames:
            with open(os.path.join(dirpath, "qwebchannel.js"), encoding="utf-8") as f:
                return f.read() + "\n" + _QWEBCHANNEL_INJECT_JS
    return _QWEBCHANNEL_INJECT_JS


class WebView(QWebEngineView if WEBENGINE_AVAILABLE else QWidget):  # type: ignore[misc]
    """
    Web 引擎控件（基于 Chromium 的 QtWebEngine 封装）。

    继承自 QWebEngineView，可直接当普通控件放进布局里渲染网页、本地文件
    或 HTML 字符串。相比裸用 QWebEngineView，这里做了三件事：

    1. **主题适配**：页面底色取自 theme_manager 的 web_bg 键，切主题时由
       apply_theme() 自动刷新，深色主题下不会出现刺眼的白底。
    2. **信号收敛**：把 Qt 分散的信号统一转发成参数为基本类型的 NanUI
       风格信号（loadStarted / loadFinished / titleChanged / urlChanged）。
    3. **扩展能力**：
       - 导航拦截：域名黑名单或全局外链拦截，被拦时发射 navigationBlocked；
       - JS → Python 消息通道：一个零依赖的 ``NanUI.postMessage(text)`` 已
         自动注入所有 frame（底层走 QWebChannel 协议），页面里直接调用：

             NanUI.postMessage("hello");   // Python 侧收到 messageReceived

         Python → JS 方向用 runJavaScript()，或自行引入 Qt 官方
         qwebchannel.js 连接 ``NanUI.transport`` 使用完整的 ``nanui`` 桥对象。

    环境中没有 PySide6 的 WebEngine 组件时，``import NanUI`` 不会崩溃，
    WebView 退化为占位 QWidget，只有真正构造时才抛出带安装提示的
    RuntimeError；可用 ``NanUI.WEBENGINE_AVAILABLE`` 提前探测。

    Args:
        parent (QWidget, optional): 父控件对象。默认为 None。
        url (str, optional): 初始加载的网址、file:// 地址或本地文件路径。
            默认为 None，即空白页。
        transparent (bool): 是否让页面底色透明（叠在窗口背景上）。默认 False。

    Signals:
        loadStarted(): 开始加载页面。
        loadFinished(bool): 页面加载结束，参数为是否成功。
        titleChanged(str): 页面标题变化。
        urlChanged(str): 页面地址变化。
        navigationBlocked(str): 导航被拦截，参数为被阻止的地址。
        messageReceived(str): 收到页面通过 NanUI.postMessage(...) 发来的消息。
    """

    loadStarted = Signal()
    loadFinished = Signal(bool)
    titleChanged = Signal(str)
    urlChanged = Signal(str)
    navigationBlocked = Signal(str)
    messageReceived = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        url: Optional[str] = None,
        transparent: bool = False,
    ) -> None:
        if not WEBENGINE_AVAILABLE:
            raise RuntimeError(WEBENGINE_HINT)
        super().__init__(parent)

        self._transparent = transparent
        self._block_external = False
        self._blocked_hosts: set[str] = set()

        page = self.page()

        # --- 主题底色（paintEvent 阶段生效，页面没设 body 背景也不露白）---
        self.apply_theme_colors()

        # --- Qt 信号 → NanUI 风格信号（统一转成基本类型，方便纯 Python 消费）---
        page.loadStarted.connect(self.loadStarted)
        page.loadFinished.connect(self.loadFinished)
        page.titleChanged.connect(self.titleChanged)
        super().urlChanged.connect(lambda qurl: self.urlChanged.emit(qurl.toString()))

        # --- 导航拦截钩子（Qt 6.4+ 提供；老版本静默跳过该功能）---
        try:
            page.profile().requestSuspensionRequested.connect(
                self._on_suspension_requested
            )
        except AttributeError:
            pass

        # --- JS ↔ Python 消息通道 ---
        self._bridge = _JsBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("nanui", self._bridge)
        page.setWebChannel(self._channel)
        self._inject_qwebchannel(page)

        if url is not None:
            self.setUrl(url)

    # ---------- 公开接口 ----------

    def setUrl(self, url: Union[str, QUrl]) -> None:  # 覆盖以接受 str
        """加载页面。参数可以是 str（http/file/本地路径）或 QUrl。"""
        if isinstance(url, str):
            url = self._to_qurl(url)
        super().setUrl(url)

    def setHtml(self, html: str, baseUrl: str = "about:blank") -> None:
        """加载一段 HTML 字符串（如内嵌文档、富文本预览）。"""
        super().setHtml(html, self._to_qurl(baseUrl))

    def runJavaScript(self, code: str) -> None:
        """在页面上下文中执行 JavaScript（Python → JS 的一次性求值）。"""
        self.page().runJavaScript(code)

    def stopLoading(self) -> None:
        """中断当前加载。"""
        self.page().stop()

    def isLoading(self) -> bool:
        """页面是否仍在加载。"""
        return self.page().isLoading()

    def postMessage(self, message: str) -> None:
        """向页面广播一条消息（JS 侧 nanui.message.connect 注册的回调会收到）。"""
        self._bridge.message.emit(str(message))

    # ---------- 导航拦截 ----------

    def blockExternalNavigation(self, blocked: bool = True) -> None:
        """开启/关闭全局外链拦截（阻止一切 http/https 跳转）。"""
        self._block_external = blocked

    def addBlockedHost(self, host: str) -> None:
        """加入域名黑名单：导航到该域名（含子域）时被阻止并发射 navigationBlocked。"""
        self._blocked_hosts.add(host.lower())

    def clearBlockedHosts(self) -> None:
        """清空域名黑名单。"""
        self._blocked_hosts.clear()

    @Slot(QWebEngineNavigationRequest)
    def _on_suspension_requested(self, request: Any) -> None:
        """Qt 在每次导航前调用；按黑名单/全局开关决定放行还是取消。"""
        url = request.url().toString().lower()
        blocked = self._block_external and url.startswith(("http://", "https://"))
        if not blocked:
            blocked = any(host in url for host in self._blocked_hosts)
        if blocked:
            request.action = QWebEngineNavigationRequest.Action.Cancel
            self.navigationBlocked.emit(request.url().toString())

    # ---------- 主题适配 ----------

    def apply_theme_colors(self) -> None:
        """把当前主题的 web_bg 颜色写进页面底色；切主题后由 apply_theme 再调。"""
        if self._transparent:
            self.page().setBackgroundColor(Qt.GlobalColor.transparent)
        else:
            self.page().setBackgroundColor(QColor(get_color("web_bg")))

    # ---------- 内部工具 ----------

    def _inject_qwebchannel(self, page: Any) -> None:
        """把 qwebchannel.js 以 DocumentCreation 时机注入所有 frame。"""
        script = QWebEngineScript()
        script.setName("nanui-qwebchannel")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(_load_qwebchannel_source())
        page.scripts().insert(script)

    @staticmethod
    def _to_qurl(url: str) -> QUrl:
        """字符串转 QUrl：本地路径自动加 file:// 前缀。"""
        if url.startswith(("http://", "https://", "file://", "data:", "about:")):
            return QUrl(url)
        return QUrl.fromLocalFile(url)


class _JsBridge(QObject):
    """
    暴露给页面的桥对象（在 QWebChannel 里注册为 ``nanui``）。

    - JS → Python：页面经 NanUI.postMessage / nanui.send 调用本槽，转发为
      WebView.messageReceived；
    - Python → JS：WebView.postMessage(text) 触发 message 信号，页面里
      ``nanui.message.connect(handler)`` 注册的回调会被调用。
    """

    message = Signal(str)

    def __init__(self, view: "WebView") -> None:
        super().__init__(view)
        self._view = view

    @Slot(str, result=None)
    def send(self, message: str) -> None:
        """JS 侧入口：把字符串消息转发给 WebView.messageReceived。"""
        self._view.messageReceived.emit(str(message))

# PxEngine: PerimeterX 验证码自动求解引擎

`pxbypass` 是 CloakBrowser 的 PerimeterX (PX) 验证码自动求解模块。采用类层次架构，支持多种检测策略和求解策略的灵活组合。

## 目录结构

```
pxbypass/
├── README.md              ← 本文档
├── __init__.py            ← 对外 API（patch_browser, detect_px, solve_px, PxEngine）
├── config.py              ← PxConfig 配置类
│
├── engine.py              ← PxEngine: 自动识别PX类型 → 调度求解流程
│
├── detector.py            ← （旧版）向后兼容的单文件 detector
├── solver.py              ← （旧版）向后兼容的单文件 solver
│
├── detect/                ← 检测策略（每个策略一个类）
│   ├── __init__.py
│   ├── base.py            ← BaseDetector (ABC) + DetectResult
│   ├── keyword.py         ← DetectPxByKeyword: 页面文本关键词扫描
│   ├── dom_element.py     ← DetectPxByDomElement: DOM 元素检查
│   ├── script_src.py      ← DetectPxByScriptSrc: 脚本 URL 检查
│   ├── url_pattern.py     ← DetectPxByUrlPattern: URL 模式匹配
│   ├── globals.py         ← DetectPxByGlobals: JS 全局变量检查
│   └── composite.py       ← CompositeDetector + DetectMode
│
├── solve/                 ← 求解策略（每个策略一个类）
│   ├── __init__.py
│   ├── base.py            ← BaseSolver (ABC) + SolveResult + HoldTarget
│   ├── press_hold_button.py   ← SolveByHoldButton: 文本定位 → 按住
│   ├── press_hold_container.py ← SolveByHoldContainer: 容器定位 → 按住
│   └── composite.py       ← CompositeSolver: 按优先级尝试多个求解器
│
└── site/                  ← 网站专属配置（组合检测器+求解器）
    ├── __init__.py
    ├── base.py            ← SiteHandler (ABC)
    ├── walmart.py         ← WalmartHandler: 3种检测 + 2种求解
    └── ifood.py           ← IfoodHandler: 2种检测 + 1种求解
```

## 快速使用

```python
from cloakbrowser import launch

# 加一个参数即可
browser = launch(bypass_px=True)
page = browser.new_page()
page.goto("https://target-with-px.com")
# 遇到 PX 挑战会自动检测并求解
# 后台持续监控，不管 PX 在 1 分钟后还是 10 分钟后触发，都能自动过掉
```

## 工作原理

`bypass_px=True` 会在浏览器层面打补丁，拦截所有新页面的创建。每个页面创建时：

1. **立即启动后台监控** — daemon 线程（sync API）或 asyncio task（async API）
2. 每 `monitor_interval` 秒（默认 1.5s）用 JS 快速探测页面 DOM
3. 一旦发现 PX 挑战 UI，立即自动检测挑战类型并执行按住求解
4. 页面关闭后监控自动停止

监控覆盖所有页面，无论导航方式：`goto()`、点击链接、SPA 路由跳转、`window.location` 等均不受影响。

## PxEngine 高级用法

```python
from cloakbrowser.pxbypass import PxEngine, PxConfig
from cloakbrowser.pxbypass.site import WalmartHandler, IfoodHandler

# 创建引擎
engine = PxEngine(PxConfig(
    max_attempts=5,
    hold_min=3.5,
    hold_max=6.0,
    post_wait=30.0,
))

# 注册网站处理器（优先级高的先匹配）
engine.register_handler(WalmartHandler())  # priority=10
engine.register_handler(IfoodHandler())    # priority=10

# detect → solve 两步
handler, detect_result = engine.detect(page)
if detect_result.detected:
    solve_result = engine.solve(page, handler, detect_result)
    print(f"{'Solved' if solve_result.solved else 'Failed'} via {solve_result.method}"
          f" ({solve_result.attempts} attempts, {solve_result.duration:.1f}s)")
else:
    print("No PX detected")

# 手动检查并求解（不等待）
if engine.check_and_solve(page):
    print("PX solved!")
```

## 扩展指南

### 添加新的检测方式

新建一个类，继承 `BaseDetector`，实现 `detect(page) → DetectResult`：

```python
# pxbypass/detect/shadow_dom.py
from .base import BaseDetector, DetectResult

class DetectPxByShadowDom(BaseDetector):
    """检测 PX 是否藏在 shadow DOM 中."""

    def detect(self, page) -> DetectResult:
        found = page.evaluate("""() => {
            const hosts = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.shadowRoot && el.shadowRoot.querySelector('#px-captcha'))
                    hosts.push(el.tagName);
            });
            return hosts;
        }""")
        if found:
            return DetectResult(
                detected=True,
                confidence=0.8,
                evidence={"shadow_hosts": found},
            )
        return DetectResult()
```

然后在 site handler 中组合使用：

```python
from ..detect.shadow_dom import DetectPxByShadowDom

class MySiteHandler(SiteHandler):
    def build_detector(self):
        return CompositeDetector([
            DetectPxByKeyword(["key phrase"]),
            DetectPxByShadowDom(),  # ← 新增
        ])
```

### 添加新的求解方式

```python
# pxbypass/solve/custom_solver.py
from .base import BaseSolver, SolveResult, HoldTarget

class SolveByCustom(BaseSolver):
    def solve(self, page, cfg, detect_result=None) -> SolveResult:
        # 自定义求解逻辑
        return SolveResult(solved=True, method="SolveByCustom")
```

### 添加新的网站

```python
# pxbypass/site/mysite.py
from ..detect.composite import CompositeDetector
from ..detect.keyword import DetectPxByKeyword
from ..solve.composite import CompositeSolver
from ..solve.press_hold_button import SolveByHoldButton
from .base import SiteHandler

class MySiteHandler(SiteHandler):
    name = "mysite"
    priority = 10  # 数值越大越优先

    def build_detector(self):
        return CompositeDetector([
            DetectPxByKeyword(["press and hold", "verify you're human"]),
        ])

    def build_solver(self):
        return CompositeSolver([
            SolveByHoldButton(["Press and hold"]),
            SolveByHoldContainer("#px-captcha"),
        ])
```

注册即可使用：

```python
from cloakbrowser.pxbypass.site.mysite import MySiteHandler
engine.register_handler(MySiteHandler())
```

## 检测策略参考

| 策略类 | 检测方式 | 适用场景 | 典型置信度 |
|--------|----------|----------|:---:|
| `DetectPxByKeyword` | 页面文本关键词 | 所有 PX 变体 | 0.5~0.9 |
| `DetectPxByDomElement` | DOM 元素选择器 | 有 #px-captcha 等元素 | 0.85 |
| `DetectPxByScriptSrc` | 页面脚本 URL | Cloud 版本 PX | 0.75~0.9 |
| `DetectPxByUrlPattern` | 当前页面 URL | 路径含 /blocked 等 | 0.7 |
| `DetectPxByGlobals` | JS 全局变量 | PX SDK 已加载 | 0.6 |

## 求解策略参考

| 策略类 | 求解方式 | 适用场景 |
|--------|----------|----------|
| `SolveByHoldButton` | 文本定位按钮 → 贝塞尔曲线移动 → 按住 3~6秒 | iframe modal 变体 (iFood) |
| `SolveByHoldContainer` | 容器位置定位 → 模拟按住 | 跨域 cloud 变体 (Walmart) |

## PxConfig 参数

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `enabled` | `True` | 是否启用自动求解 |
| `max_attempts` | `3` | 最大尝试次数 |
| `hold_min` | `3.8` | 最短按住时间(秒) |
| `hold_max` | `6.5` | 最长按住时间(秒) |
| `post_wait` | `30.0` | 松开后等待 UI 消失(秒) |
| `ui_wait_timeout` | `45.0` | 首次检测时等待 PX UI 出现的超时(秒) |
| `button_wait_timeout` | `20.0` | 等待按钮出现超时(秒) |
| `monitor_interval` | `1.5` | 后台监控轮询间隔(秒)，越小检测越快但 CPU 略高 |
| `reload_if_hidden` | `True` | PX 未显示时是否刷新页面 |
| `checker` | `None` | 可选验证回调 `(page) → bool` |

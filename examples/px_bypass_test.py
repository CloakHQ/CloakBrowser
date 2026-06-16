"""PerimeterX (PX) 验证码自动求解测试示例。

测试目标: https://www.walmart.com/blocked?url=Lw==
Walmart 使用 PerimeterX 的 "Activate and hold" 验证码，
验证码通过跨域 iframe (px-cloud.net) 加载。

用法:
    python examples/px_bypass_test.py

说明:
    该示例测试 CloakBrowser 的 bypass_px=True 功能。
    如果 PX 验证码成功通过，页面内容会变为正常的 Walmart 首页。
    如果验证失败，页面会停留在 "Robot or human?" 拦截页。

注意:
    PX 验证码自动求解是实验性功能，成功率受网络、IP、浏览器等因素影响。
    失败时外层代码应换 IP 并重试。
"""

import logging
import sys
import time
from pathlib import Path

# 设置日志，便于观察 PX 求解过程
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

# 让 cloakbrowser.pxbypass 的日志更详细
logging.getLogger("cloakbrowser.pxbypass").setLevel(logging.DEBUG)

from cloakbrowser import launch
from cloakbrowser.pxbypass import detect_px
from cloakbrowser.pxbypass.config import PxConfig


TARGET_URL = (
    "https://www.walmart.com/blocked"
    "?url=Lw=="
    "&uuid=7883d050-4d11-11ec-8c63-8fa6a26a652a"
    "&vid=a0f5dbf2-3c8c-11ec-b175-787445664d76"
    "&g=b"
)


def test_px_bypass(headless: bool = True) -> bool:
    """测试 PX 验证码自动求解。

    流程：
        1. 启动 CloakBrowser（带 bypass_px=True）
        2. 访问 Walmart 的 PX 拦截页
        3. bypass_px 会自动检测 PX 挑战
        4. 执行 "Activate and hold" 验证
        5. 验证通过后页面应跳转到 Walmart 首页

    Args:
        headless: 是否无头模式。设为 False 可观察浏览器操作。

    Returns:
        True 表示 PX 验证成功，False 表示验证失败。
    """
    screenshot_dir = Path("/tmp/cloakbrowser_px_test")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("PerimeterX 自动求解测试")
    print("=" * 60)
    print(f"目标URL: {TARGET_URL}")
    print(f"Headless: {headless}")
    print()

    # 自定义 PX 配置（可根据需要调整）
    px_config = PxConfig(
        max_attempts=3,          # 最多尝试 3 次
        hold_min=3.5,            # 最短按住 3.5 秒
        hold_max=6.0,            # 最长按住 6.0 秒
        post_wait=30.0,          # 松开后最多等 30 秒
        button_wait_timeout=25.0, # 等待按钮出现最多 25 秒
        reload_if_hidden=True,   # 如果没看到 PX UI 就刷新页面
    )

    browser = launch(
        headless=headless,
        bypass_px=True,
        px_config=px_config,
    )

    page = browser.new_page()

    # 阶段1: 访问目标页面
    print("\n[阶段1] 正在访问 Walmart PX 拦截页...")
    try:
        page.goto(TARGET_URL, timeout=90_000, wait_until="load")
    except Exception as e:
        print(f"  ⚠ 页面加载超时（这在 PX 页面常见）: {e}")

    # 阶段2: 等待 PX 检测与求解
    print("\n[阶段2] 等待 PX 检测与自动求解...")
    print("  (bypass_px 已启用，检测到 PX 后会自动执行按住验证)")

    # 等待 15 秒给 PX 求解足够时间
    for i in range(30):
        time.sleep(1)
        current_url = page.url
        title = page.title()

        # 截图保存当前状态
        if i % 5 == 0:
            screenshot_path = screenshot_dir / f"step_{i:02d}.png"
            try:
                page.screenshot(path=str(screenshot_path))
                print(f"  截图已保存: {screenshot_path}")
            except Exception:
                pass

        # 检测是否已通过 PX (页面跳转到了正常的 Walmart 页面)
        if "walmart.com/blocked" not in current_url and "walmart.com" in current_url:
            print(f"\n  ✅ PX 已通过! 当前页面: {current_url}")
            print(f"  页面标题: {title}")
            page.screenshot(path=str(screenshot_dir / "px_passed.png"))
            browser.close()
            return True

        # 每 5 秒打印一次状态
        if i % 5 == 0:
            px_detected = detect_px(page)
            print(f"  [{i}s] 标题={title[:60]}, PX检测={px_detected}, URL长度={len(current_url)}")

    # 超时检查最终状态
    print("\n[阶段3] 超时 - 检查最终状态")
    final_url = page.url
    final_title = page.title
    px_still_detected = detect_px(page)

    print(f"  最终 URL: {final_url}")
    print(f"  最终标题: {final_title}")
    print(f"  PX 检测: {px_still_detected}")
    page.screenshot(path=str(screenshot_dir / "final.png"))

    result = "walmart.com/blocked" not in final_url

    browser.close()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PerimeterX 自动求解测试")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="使用有头模式（可观察浏览器操作）",
    )
    args = parser.parse_args()

    success = test_px_bypass(headless=not args.headed)

    print()
    print("=" * 60)
    if success:
        print("  ✅ 测试通过: PX 验证码已成功解决")
    else:
        print("  ❌ 测试失败: PX 验证码未能在超时内解决")
        print()
        print("  可能的原因:")
        print("  1. 网络环境问题 - 尝试使用住宅代理")
        print("  2. PX 已更新验证逻辑 - 需要更新求解器")
        print("  3. 当前 IP 被 PX 标记 - 换 IP 重试")
        print("  4. 按住时间/次数需要调整 - 修改 px_config")
    print("=" * 60)

    sys.exit(0 if success else 1)
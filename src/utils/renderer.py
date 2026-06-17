"""本地 HTML 图片渲染器。"""
import tempfile

import jinja2
from astrbot.api import logger


class LocalHtmlRenderer:
    _playwright_instance = None
    _playwright_browser = None

    @classmethod
    async def get_browser(cls):
        if cls._playwright_browser and cls._playwright_browser.is_connected():
            return cls._playwright_browser
        try:
            from playwright.async_api import async_playwright
            if cls._playwright_instance is None:
                cls._playwright_instance = await async_playwright().start()
            if cls._playwright_browser is None or not cls._playwright_browser.is_connected():
                cls._playwright_browser = await cls._playwright_instance.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-gpu'],
                )
            return cls._playwright_browser
        except Exception as e:
            logger.warning(f"Playwright 不可用: {e}")
            return None

    async def render(self, html_content, data=None, options=None, cache_dir=None):
        browser = await self.get_browser()
        if not browser:
            return None

        page = None
        try:
            if data:
                tmpl = jinja2.Template(html_content)
                rendered_html = tmpl.render(**data)
            else:
                rendered_html = html_content

            page = await browser.new_page(viewport={"width": 1200, "height": 2000})
            await page.set_content(rendered_html, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(1000)
            try:
                await page.wait_for_function("() => typeof echarts !== 'undefined'", timeout=8000)
                await page.wait_for_function(
                    "() => { const chart = document.querySelector('div[_echarts_instance_]'); return chart && chart.clientWidth > 0; }",
                    timeout=3000,
                )
                await page.wait_for_timeout(500)
            except Exception as e:
                logger.debug(f"ECharts 等待超时或非 ECharts 页面: {e}")

            content_box = await page.evaluate("""() => {
                const body = document.body;
                const bodyRect = body.getBoundingClientRect();
                let right = bodyRect.right;
                let bottom = bodyRect.bottom;

                for (const el of body.querySelectorAll('*')) {
                    const rect = el.getBoundingClientRect();
                    if (!rect.width && !rect.height) continue;
                    right = Math.max(right, rect.right);
                    bottom = Math.max(bottom, rect.bottom);
                }

                return {
                    x: 0,
                    y: 0,
                    width: Math.max(1, Math.ceil(right)),
                    height: Math.max(1, Math.ceil(bottom)),
                };
            }""")

            opts = options or {}
            screenshot_opts = {
                "type": opts.get("type", "png"),
                "clip": {
                    "x": content_box["x"],
                    "y": content_box["y"],
                    "width": content_box["width"],
                    "height": content_box["height"],
                },
            }
            if opts.get("quality"):
                screenshot_opts["quality"] = opts["quality"]

            img_bytes = await page.screenshot(**screenshot_opts)
            suffix = ".jpg" if screenshot_opts["type"] == "jpeg" else ".png"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=cache_dir)
            tmp.write(img_bytes)
            tmp.close()
            return tmp.name

        except Exception as e:
            logger.warning(f"本地 Playwright 渲染失败: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    @classmethod
    async def close(cls):
        if cls._playwright_browser:
            try:
                await cls._playwright_browser.close()
            except Exception:
                pass
            cls._playwright_browser = None
        if cls._playwright_instance:
            try:
                await cls._playwright_instance.stop()
            except Exception:
                pass
            cls._playwright_instance = None

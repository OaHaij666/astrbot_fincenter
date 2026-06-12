"""FinCenter 图片渲染模块

使用 Playwright 无头浏览器渲染 HTML 模板并截图，
替代 PIL/matplotlib 手绘方案，获得更好的美术效果。
K线图使用 ECharts 专业金融图表库。
"""
import io
import os
import hashlib
import base64
import logging
import asyncio
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_assets_dir = os.path.join(_base_dir, 'assets')
_data_dir = os.path.join(_base_dir, 'data')
_templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
_cache_dir = os.path.join(_data_dir, 'cache')
_help_cache_dir = os.path.join(_data_dir, 'cache', 'help')
_echarts_path = os.path.join(_assets_dir, 'js', 'echarts.min.js')

_mem_path_cache_key = None
_mem_path_cache_val = None

# Playwright 浏览器实例（懒加载，全局复用）
_browser = None
_playwright = None
_browser_lock = asyncio.Lock() if hasattr(asyncio, 'Lock') else None

# Jinja2 环境
_jinja_env = None

# 帮助图缓存：跟踪当前进程生成过的 hash，上限 = 已知种类数 + 2
_help_hash_set = set()


def set_paths(base_dir: str = None, assets_dir: str = None, data_dir: str = None):
    global _base_dir, _assets_dir, _data_dir, _cache_dir, _help_cache_dir, _templates_dir, _jinja_env, _echarts_path
    if base_dir:
        _base_dir = base_dir
        _assets_dir = os.path.join(_base_dir, 'assets')
        _data_dir = os.path.join(_base_dir, 'data')
    if assets_dir:
        _assets_dir = assets_dir
    if data_dir:
        _data_dir = data_dir
    _cache_dir = os.path.join(_data_dir, 'cache')
    _help_cache_dir = os.path.join(_data_dir, 'cache', 'help')
    _templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
    _echarts_path = os.path.join(_assets_dir, 'js', 'echarts.min.js')
    _jinja_env = Environment(
        loader=FileSystemLoader(_templates_dir),
        autoescape=select_autoescape(['html', 'xml']),
    )


def _get_jinja():
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(_templates_dir),
            autoescape=select_autoescape(['html', 'xml']),
        )
    return _jinja_env


# ===== 缓存机制 =====

def _get_mem_cached_image(data_hash: str):
    global _mem_path_cache_key, _mem_path_cache_val
    if _mem_path_cache_key == data_hash and _mem_path_cache_val:
        if os.path.exists(_mem_path_cache_val):
            return _mem_path_cache_val
    return None


def _set_mem_cached_image(data_hash: str, path: str):
    global _mem_path_cache_key, _mem_path_cache_val
    _mem_path_cache_key = data_hash
    _mem_path_cache_val = path


def _get_cache_key(data_hash: str) -> str:
    return os.path.join(_cache_dir, f"{data_hash}.png")


def _get_cached_image(data_hash: str):
    if not os.path.exists(_cache_dir):
        return None
    cached = _get_mem_cached_image(data_hash)
    if cached:
        return cached
    path = _get_cache_key(data_hash)
    if os.path.exists(path):
        _set_mem_cached_image(data_hash, path)
        return path
    return None


def _save_cached_image(data_hash: str, buf: io.BytesIO) -> str:
    if not os.path.exists(_cache_dir):
        os.makedirs(_cache_dir, exist_ok=True)
    path = _get_cache_key(data_hash)
    with open(path, 'wb') as f:
        f.write(buf.getvalue())
    _set_mem_cached_image(data_hash, path)
    return path


def _clean_cache(max_files=30):
    _clean_dir(_cache_dir, max_files)


def _clean_help_cache(max_files=10):
    _clean_dir(_help_cache_dir, max_files)


def _clean_dir(directory: str, max_files: int):
    if not os.path.exists(directory):
        return
    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.png')]
    if len(files) > max_files:
        files.sort(key=os.path.getmtime)
        for old in files[:len(files) - max_files]:
            try:
                os.remove(old)
            except Exception:
                pass


# ===== 帮助图专用缓存（动态上限：已知种类数+2） =====

def _get_help_cache_key(data_hash: str) -> str:
    return os.path.join(_help_cache_dir, f"{data_hash}.png")


def _get_cached_help_image(data_hash: str):
    cached = _get_mem_cached_image(data_hash)
    if cached:
        _help_hash_set.add(data_hash)
        return cached
    path = _get_help_cache_key(data_hash)
    if os.path.exists(path):
        _set_mem_cached_image(data_hash, path)
        _help_hash_set.add(data_hash)
        return path
    return None


def _save_cached_help_image(data_hash: str, buf: io.BytesIO) -> str:
    if not os.path.exists(_help_cache_dir):
        os.makedirs(_help_cache_dir, exist_ok=True)
    path = _get_help_cache_key(data_hash)
    with open(path, 'wb') as f:
        f.write(buf.getvalue())
    _set_mem_cached_image(data_hash, path)
    _help_hash_set.add(data_hash)
    # 动态上限：当前已知帮助种类数 + 2，热更新后旧僵尸自然被 LRU 淘汰
    _clean_help_cache(max_files=len(_help_hash_set) + 2)
    return path


def _compute_hash(*args) -> str:
    h = hashlib.md5()
    for arg in args:
        h.update(str(arg).encode('utf-8'))
    return h.hexdigest()


# ===== Playwright 浏览器管理 =====

async def _get_browser():
    """获取或创建 Playwright 浏览器实例（懒加载，全局复用）
    优先使用系统 Edge/Chrome 浏览器，无需下载 Chromium。
    """
    global _browser, _playwright
    if _browser and _browser.is_connected():
        return _browser
    if _browser_lock is not None:
        async with _browser_lock:
            # Double-check after acquiring lock
            if _browser and _browser.is_connected():
                return _browser
            try:
                from playwright.async_api import async_playwright
                _playwright = await async_playwright().start()
                # 尝试使用系统浏览器（Edge > Chrome），避免下载 Chromium
                for channel in ['msedge', 'chrome']:
                    try:
                        _browser = await _playwright.chromium.launch(
                            headless=True,
                            channel=channel,
                            args=['--no-sandbox', '--disable-gpu', '--font-render-hinting=none'],
                        )
                        logger.info(f"Playwright browser launched (channel={channel})")
                        return _browser
                    except Exception:
                        continue
                # 回退到下载的 Chromium
                _browser = await _playwright.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-gpu', '--font-render-hinting=none'],
                )
                logger.info("Playwright browser launched (chromium)")
                return _browser
            except Exception as e:
                logger.error(f"Failed to launch Playwright browser: {e}")
                raise
    else:
        try:
            from playwright.async_api import async_playwright
            _playwright = await async_playwright().start()
            for channel in ['msedge', 'chrome']:
                try:
                    _browser = await _playwright.chromium.launch(
                        headless=True,
                        channel=channel,
                        args=['--no-sandbox', '--disable-gpu', '--font-render-hinting=none'],
                    )
                    logger.info(f"Playwright browser launched (channel={channel})")
                    return _browser
                except Exception:
                    continue
            _browser = await _playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-gpu', '--font-render-hinting=none'],
            )
            logger.info("Playwright browser launched (chromium)")
            return _browser
        except Exception as e:
            logger.error(f"Failed to launch Playwright browser: {e}")
            raise


async def _screenshot_html(html_content: str, width: int = 800, full_page: bool = True) -> bytes:
    """将 HTML 内容渲染为 PNG 截图

    使用临时文件方式加载 HTML，以支持本地 JS/CSS/图片资源的引用。

    Args:
        html_content: 完整的 HTML 字符串
        width: 视口宽度（像素）
        full_page: 是否截取完整页面

    Returns:
        PNG 图片的 bytes 数据
    """
    browser = await _get_browser()
    context = await browser.new_context(
        viewport={'width': width, 'height': 600},
        device_scale_factor=2,
    )
    page = await context.new_page()

    try:
        # 写入临时 HTML 文件，以便本地资源可以被正确加载
        import tempfile
        fd, tmp_html = tempfile.mkstemp(suffix='.html')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(html_content)
            # Windows 路径需要转换为 file:// URL
            file_url = 'file:///' + os.path.abspath(tmp_html).replace('\\', '/')
            await page.goto(file_url, wait_until='networkidle', timeout=15000)
        finally:
            try:
                os.remove(tmp_html)
            except Exception:
                pass

        # 等待 ECharts 渲染完成
        await page.wait_for_timeout(500)
        screenshot = await page.screenshot(
            full_page=full_page,
            type='png',
        )
        return screenshot
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        raise
    finally:
        await context.close()


async def _screenshot_html_file(html_path: str, width: int = 800, full_page: bool = True) -> bytes:
    """从 HTML 文件路径渲染截图"""
    browser = await _get_browser()
    context = await browser.new_context(
        viewport={'width': width, 'height': 600},
        device_scale_factor=2,
    )
    page = await context.new_page()

    try:
        file_url = 'file:///' + os.path.abspath(html_path).replace('\\', '/')
        await page.goto(file_url, wait_until='networkidle', timeout=15000)
        await page.wait_for_timeout(500)
        screenshot = await page.screenshot(
            full_page=full_page,
            type='png',
        )
        return screenshot
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        raise
    finally:
        await context.close()


# ===== 渲染函数 =====

async def plot_kline(history_list, title="K线走势", tech_levels=None, max_candles=50, font_key=None):
    """绘制 K 线图 — 使用 ECharts 渲染

    Args:
        history_list: 历史K线数据列表，每项包含 date/open/high/low/close/volume
        title: 图表标题
        tech_levels: 技术指标，包含 ma5/ma20/support/resistance
        max_candles: 最大K线数量
        font_key: 字体键（保留兼容，暂不使用）

    Returns:
        io.BytesIO 包含 PNG 图片数据，失败返回 None
    """
    if not history_list:
        return None

    candles = history_list[-max_candles:] if len(history_list) > max_candles else history_list

    data_hash = _compute_hash(title, str(candles), str(tech_levels), max_candles, font_key)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    # 准备 ECharts 数据
    dates = []
    ohlc = []
    volumes = []
    ma5_data = []
    ma20_data = []

    for c in candles:
        dates.append(c['date'])
        ohlc.append([c['open'], c['close'], c['low'], c['high']])
        volumes.append(c.get('volume', 0))

    # 技术指标
    if tech_levels:
        if 'ma5' in tech_levels and tech_levels['ma5']:
            ma5_raw = tech_levels['ma5'][-len(candles):]
            ma5_data = ma5_raw if len(ma5_raw) == len(candles) else []
        if 'ma20' in tech_levels and tech_levels['ma20']:
            ma20_raw = tech_levels['ma20'][-len(candles):]
            ma20_data = ma20_raw if len(ma20_raw) == len(candles) else []

    support_levels = []
    resistance_levels = []
    if tech_levels:
        if 'support' in tech_levels and tech_levels['support']:
            support_levels = tech_levels['support']
        if 'resistance' in tech_levels and tech_levels['resistance']:
            resistance_levels = tech_levels['resistance']

    # 渲染模板
    if os.path.exists(_echarts_path):
        echarts_src = 'file:///' + os.path.abspath(_echarts_path).replace('\\', '/')
    else:
        echarts_src = 'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'
    env = _get_jinja()
    template = env.get_template('kline.html')
    html_content = template.render(
        title=title,
        dates=dates,
        ohlc=ohlc,
        volumes=volumes,
        ma5=ma5_data,
        ma20=ma20_data,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        echarts_path=echarts_src,
    )

    try:
        png_bytes = await _screenshot_html(html_content, width=800)
        buf = io.BytesIO(png_bytes)
        _save_cached_image(data_hash, buf)
        _clean_cache()
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"K-line rendering failed: {e}")
        return None


async def render_stock_market_image(market_data, holdings=None, news=None,
                                     currency_name="金币", currency_icon="💰",
                                     kline_images=None, font_key=None):
    """渲染股市总览图片

    Args:
        market_data: 行情数据列表
        holdings: 持仓数据列表
        news: 新闻数据列表
        currency_name: 货币名称
        currency_icon: 货币图标
        kline_images: K线图字典 {code: BytesIO}
        font_key: 字体键（保留兼容）

    Returns:
        io.BytesIO 包含 PNG 图片数据
    """
    data_hash = _compute_hash(str(market_data), str(holdings), str(news),
                              currency_name, currency_icon,
                              str(kline_images) if kline_images else None, font_key)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    # 将 K 线图 BytesIO 转为 base64 嵌入 HTML
    kline_b64 = {}
    if kline_images:
        for code, img_buf in kline_images.items():
            try:
                img_buf.seek(0)
                img_data = img_buf.read()
                kline_b64[code] = base64.b64encode(img_data).decode('utf-8')
            except Exception:
                pass

    # 处理新闻数据
    news_list = []
    if news:
        for n in news:
            news_list.append({
                'content': n.get('content', n.get('title', ''))[:80],
            })

    env = _get_jinja()
    template = env.get_template('stock_market.html')
    html_content = template.render(
        market_data=market_data or [],
        holdings=holdings or [],
        news=news_list,
        kline_images=kline_b64,
        currency_name=currency_name,
        currency_icon=currency_icon,
    )

    try:
        png_bytes = await _screenshot_html(html_content, width=800)
        buf = io.BytesIO(png_bytes)
        _save_cached_image(data_hash, buf)
        _clean_cache()
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Stock market image rendering failed: {e}")
        # 返回一个简单的错误图片占位
        return None


async def render_goods_market_image(goods_list, stock_data=None,
                                    currency_name="金币", currency_icon="💰"):
    """渲染物资市场图片

    Args:
        goods_list: 物资列表
        stock_data: 背包库存数据
        currency_name: 货币名称
        currency_icon: 货币图标

    Returns:
        io.BytesIO 包含 PNG 图片数据
    """
    data_hash = _compute_hash(str(goods_list), str(stock_data), currency_name, currency_icon)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    if not goods_list:
        return None

    # 预处理图片路径，将本地路径转为 file:// URL
    processed_goods = []
    for g in goods_list:
        item = dict(g)
        preview = g.get('preview_image', '')
        if preview and os.path.exists(preview):
            item['preview_image_url'] = 'file:///' + os.path.abspath(preview).replace('\\', '/')
        else:
            item['preview_image_url'] = ''
        processed_goods.append(item)

    env = _get_jinja()
    template = env.get_template('goods_market.html')
    html_content = template.render(
        goods_list=processed_goods,
        stock_data=stock_data,
        currency_name=currency_name,
        currency_icon=currency_icon,
    )

    try:
        png_bytes = await _screenshot_html(html_content, width=800)
        buf = io.BytesIO(png_bytes)
        _save_cached_image(data_hash, buf)
        _clean_cache()
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Goods market image rendering failed: {e}")
        return None


async def render_rank_image(rank_data, currency_name="金币", currency_icon="💰"):
    """渲染财富排行榜图片

    Args:
        rank_data: 排行数据列表，每项包含 user_name/total_wealth
        currency_name: 货币名称
        currency_icon: 货币图标

    Returns:
        io.BytesIO 包含 PNG 图片数据
    """
    data_hash = _compute_hash(str(rank_data), currency_name, currency_icon)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    env = _get_jinja()
    template = env.get_template('rank.html')
    html_content = template.render(
        rank_data=rank_data,
        currency_name=currency_name,
        currency_icon=currency_icon,
    )

    try:
        png_bytes = await _screenshot_html(html_content, width=600)
        buf = io.BytesIO(png_bytes)
        _save_cached_image(data_hash, buf)
        _clean_cache()
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Rank image rendering failed: {e}")
        return None


async def render_help_image(title, sections, tips=None, quick_ref=None,
                            currency_name="金币", currency_icon="💰"):
    """渲染帮助页图片

    Args:
        title: 帮助页标题
        sections: 分组列表，每项包含 section_name 和 commands
        tips: 底部提示文字列表
        quick_ref: 子菜单快捷入口
        currency_name: 货币名称
        currency_icon: 货币图标

    Returns:
        io.BytesIO 包含 PNG 图片数据
    """
    data_hash = _compute_hash(title, str(sections), str(tips), str(quick_ref))
    cached = _get_cached_help_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    env = _get_jinja()
    template = env.get_template('help.html')
    html_content = template.render(
        title=title,
        sections=sections,
        tips=tips or [],
        quick_ref=quick_ref or [],
        currency_name=currency_name,
        currency_icon=currency_icon,
    )

    try:
        png_bytes = await _screenshot_html(html_content, width=600)
        buf = io.BytesIO(png_bytes)
        _save_cached_help_image(data_hash, buf)
        _clean_help_cache()
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Help image rendering failed: {e}")
        return None


async def shutdown():
    """关闭浏览器实例，释放资源"""
    global _browser, _playwright
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    logger.info("Playwright browser closed")

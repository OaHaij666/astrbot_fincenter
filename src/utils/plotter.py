import mplfinance as mpf
import pandas as pd
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import os
import hashlib

from PIL import Image, ImageDraw, ImageFont

_base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_assets_dir = os.path.join(_base_dir, 'assets')
_data_dir = os.path.join(_base_dir, 'data')

_BUNDLED_FONT = os.path.join(_assets_dir, 'fonts', 'SourceHanSansSC-Regular.ttf')
_cache_dir = os.path.join(_data_dir, 'cache')

plt.rcParams['font.sans-serif'] = ['Source Han Sans SC', 'Microsoft YaHei', 'SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

_font_cache = {}
_mem_path_cache_key = None
_mem_path_cache_val = None

# ===== Anime Blue-White (二次元蓝白) Color Palette =====
# Background gradients
BG_TOP = (235, 245, 255)
BG_BOTTOM = (250, 252, 255)
BG_GOODS_TOP = (240, 248, 255)
BG_GOODS_BOTTOM = (250, 253, 255)
BG_RANK_TOP = (238, 243, 255)
BG_RANK_BOTTOM = (248, 250, 255)

# Card colors
CARD_FILL = (255, 255, 255, 242)
CARD_BORDER = (170, 210, 240, 180)
CARD_SHADOW = (190, 210, 235, 35)

# Text colors
TITLE_COLOR = '#4a7fa8'
SECTION_COLOR = '#5b8db8'
HEADER_COLOR = '#8aa9c4'
TEXT_DARK = '#4a5b6e'
TEXT_MUTED = '#7a8fa5'
NEWS_COLOR = '#7a8fa5'

# Accent colors
ACCENT_BLUE = '#7ec8e3'
ACCENT_PINK = '#ff9eb5'
ACCENT_PURPLE = '#c8a0e0'
ACCENT_STAR = '#b8d4e8'

# Price change colors (anime-style: pink for up, soft blue for down)
UP_COLOR = '#ff8a9c'
DOWN_COLOR = '#6fc1d9'
NEUTRAL_COLOR = '#aab8c5'

# Matplotlib K-line anime colors
MPL_UP = '#ff8a9c'
MPL_DOWN = '#6fc1d9'
MPL_UP_WICK = '#e87a8a'
MPL_DOWN_WICK = '#5ab0c9'
MPL_MA5 = '#c8a0e0'
MPL_MA20 = '#7ec8e3'
MPL_GRID = '#e8eff5'
MPL_FACE = '#f5f9ff'
MPL_FIG = '#f5f9ff'
MPL_AXES = '#c8d8e8'
MPL_TICK = '#a0b8cc'

# ===== Decorative Elements =====
DECO_STAR = '✦'
DECO_SPARKLE = '✧'
DECO_DOT = '·'
DECO_RIBBON_L = '╔'
DECO_RIBBON_R = '╗'


def set_paths(base_dir: str = None, assets_dir: str = None, data_dir: str = None):
    global _base_dir, _assets_dir, _data_dir, _BUNDLED_FONT, _cache_dir
    if base_dir:
        _base_dir = base_dir
        _assets_dir = os.path.join(_base_dir, 'assets')
        _data_dir = os.path.join(_base_dir, 'data')
    if assets_dir:
        _assets_dir = assets_dir
    if data_dir:
        _data_dir = data_dir
    _BUNDLED_FONT = os.path.join(_assets_dir, 'fonts', 'SourceHanSansSC-Regular.ttf')
    _cache_dir = os.path.join(_data_dir, 'cache')


def _get_font_path(font_key: str = None) -> str:
    if os.path.exists(_BUNDLED_FONT):
        return _BUNDLED_FONT
    return ''


def _find_cjk_font(font_key: str = None):
    font_path = _get_font_path(font_key)
    if font_path and os.path.exists(font_path):
        try:
            return FontProperties(fname=font_path)
        except Exception:
            pass
    return None


def _get_font(size=20, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    font_path = _get_font_path()
    if font_path and os.path.exists(font_path):
        try:
            font = ImageFont.truetype(font_path, size)
            _font_cache[key] = font
            return font
        except Exception:
            pass
    font = ImageFont.load_default(size)
    _font_cache[key] = font
    return font


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
    if not os.path.exists(_cache_dir):
        return
    files = [os.path.join(_cache_dir, f) for f in os.listdir(_cache_dir) if f.endswith('.png')]
    if len(files) > max_files:
        files.sort(key=os.path.getmtime)
        for old in files[:len(files) - max_files]:
            try:
                os.remove(old)
            except Exception:
                pass


def _compute_hash(*args) -> str:
    h = hashlib.md5()
    for arg in args:
        h.update(str(arg).encode('utf-8'))
    return h.hexdigest()


def _draw_bg_gradient(draw, width, height, top_color, bottom_color):
    """Draw vertical gradient background."""
    for y_pos in range(height):
        ratio = y_pos / height if height > 0 else 0
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(0, y_pos), (width, y_pos)], fill=(r, g, b, 255))


def _draw_card(draw, x, y, w, h, radius=16):
    """Draw a card with shadow effects - anime style."""
    for offset in range(3, 0, -1):
        draw.rounded_rectangle(
            [(x + offset, y + offset), (x + w + offset, y + h + offset)],
            radius=radius, fill=CARD_SHADOW
        )
    draw.rounded_rectangle(
        [(x, y), (x + w, y + h)],
        radius=radius, fill=CARD_FILL, outline=CARD_BORDER, width=2
    )


def _draw_section_divider(draw, y, x_left, x_right, color='#b8d4e8'):
    """Draw a cute section divider: — ✦ — ✦ —"""
    mid_x = (x_left + x_right) // 2
    draw.line([(x_left, y), (mid_x - 25, y)], fill=color, width=1)
    draw.line([(mid_x + 25, y), (x_right, y)], fill=color, width=1)
    # Draw star at center
    font_small = _get_font(12)
    draw.text((mid_x, y), '✦', fill='#7ec8e3', font=font_small, anchor='mm')


def _draw_corner_deco(draw, w, h, margin=12):
    """Draw small decorative corner accents."""
    deco_color = (180, 215, 240, 160)
    for cx, cy in [(margin, margin), (w - margin, margin), (margin, h - margin), (w - margin, h - margin)]:
        draw.ellipse([(cx - 3, cy - 3), (cx + 3, cy + 3)], fill=deco_color)


def plot_kline(history_list, title="K线走势", tech_levels=None, max_candles=50, font_key=None):
    """绘制 K 线图 — 蓝白二次元风格"""
    if not history_list:
        return None

    font_path = _get_font_path(font_key)
    if font_path and os.path.exists(font_path):
        try:
            mpl_font = FontProperties(fname=font_path)
        except Exception:
            mpl_font = None
    else:
        mpl_font = None

    candles = history_list[-max_candles:] if len(history_list) > max_candles else history_list

    df_data = []
    for c in candles:
        df_data.append({
            'Date': pd.to_datetime(c['date']),
            'Open': c['open'],
            'High': c['high'],
            'Low': c['low'],
            'Close': c['close'],
            'Volume': c['volume'],
        })

    df = pd.DataFrame(df_data)
    df.set_index('Date', inplace=True)

    data_hash = _compute_hash(title, str(candles), str(tech_levels), max_candles, font_key)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    apds = []
    if tech_levels:
        if 'ma5' in tech_levels and tech_levels['ma5']:
            ma5_data = tech_levels['ma5'][-len(df):]
            if len(ma5_data) == len(df):
                df['MA5'] = ma5_data
                apds.append(mpf.make_addplot(df['MA5'], color=MPL_MA5, width=0.8, alpha=0.75, ylabel='MA5'))
        if 'ma20' in tech_levels and tech_levels['ma20']:
            ma20_data = tech_levels['ma20'][-len(df):]
            if len(ma20_data) == len(df):
                df['MA20'] = ma20_data
                apds.append(mpf.make_addplot(df['MA20'], color=MPL_MA20, width=0.8, alpha=0.75, ylabel='MA20'))

    mc = mpf.make_marketcolors(up=MPL_UP, down=MPL_DOWN, edge='inherit',
                               wick={'up': MPL_UP_WICK, 'down': MPL_DOWN_WICK},
                               volume={'up': MPL_UP, 'down': MPL_DOWN},
                               inherit=False)
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle='-', gridcolor=MPL_GRID,
                           facecolor=MPL_FACE, figcolor=MPL_FIG,
                           rc={'axes.edgecolor': MPL_AXES, 'axes.linewidth': 0.6,
                               'xtick.color': MPL_TICK, 'ytick.color': MPL_TICK})

    plot_kwargs = dict(
        type='candle', volume=True,
        style=s, title=f'\n{title}',
        ylabel='价格', ylabel_lower='成交量',
        returnfig=True, figscale=1.2,
        tight_layout=True,
    )
    if apds:
        plot_kwargs['addplot'] = apds

    fig, axes = mpf.plot(df, **plot_kwargs)

    if mpl_font:
        # Use a softer blue for the title
        fig.suptitle(title, fontproperties=mpl_font, fontsize=14, fontweight='bold', color='#4a7fa8')
        for ax in axes:
            ax.yaxis.label.set_fontproperties(mpl_font)
            ax.xaxis.label.set_fontproperties(mpl_font)
            ax.title.set_fontproperties(mpl_font)
            for label in ax.get_xticklabels():
                label.set_fontproperties(mpl_font)
            for label in ax.get_yticklabels():
                label.set_fontproperties(mpl_font)
            if ax.get_legend():
                for text in ax.get_legend().get_texts():
                    text.set_fontproperties(mpl_font)

    if tech_levels:
        if 'support' in tech_levels and tech_levels['support']:
            for ax in axes:
                for s_val in tech_levels['support']:
                    ax.axhline(y=s_val, color=MPL_DOWN, linestyle=':', linewidth=0.8, alpha=0.7)
                    if mpl_font:
                        ymin, ymax = ax.get_ylim()
                        mid = (ymin + ymax) / 2
                        if s_val > mid:
                            va = 'top'
                            y_offset = s_val - (ymax - ymin) * 0.01
                        else:
                            va = 'bottom'
                            y_offset = s_val + (ymax - ymin) * 0.01
                        ax.text(0.02, y_offset, f'支撑 {s_val:.1f}', transform=ax.get_yaxis_transform(),
                                color=MPL_DOWN, fontsize=8, fontproperties=mpl_font,
                                verticalalignment=va,
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.85, edgecolor='#b8d4e8', linewidth=0.5))
        if 'resistance' in tech_levels and tech_levels['resistance']:
            for ax in axes:
                for r_val in tech_levels['resistance']:
                    ax.axhline(y=r_val, color=MPL_UP, linestyle=':', linewidth=0.8, alpha=0.7)
                    if mpl_font:
                        ymin, ymax = ax.get_ylim()
                        mid = (ymin + ymax) / 2
                        if r_val > mid:
                            va = 'top'
                            y_offset = r_val - (ymax - ymin) * 0.01
                        else:
                            va = 'bottom'
                            y_offset = r_val + (ymax - ymin) * 0.01
                        ax.text(0.02, y_offset, f'阻力 {r_val:.1f}', transform=ax.get_yaxis_transform(),
                                color=MPL_UP, fontsize=8, fontproperties=mpl_font,
                                verticalalignment=va,
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.85, edgecolor='#f0c0c8', linewidth=0.5))

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)

    _save_cached_image(data_hash, buf)
    _clean_cache()

    buf.seek(0)
    return buf


def render_stock_market_image(market_data, holdings=None, news=None, currency_name="金币", currency_icon="💰", kline_images=None, font_key=None):
    data_hash = _compute_hash(str(market_data), str(holdings), str(news), currency_name, currency_icon,
                              str(kline_images) if kline_images else None, font_key)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    font_title = _get_font(30, bold=True)
    font_section = _get_font(22, bold=True)
    font_header = _get_font(17, bold=True)
    font_row = _get_font(16)
    font_news = _get_font(14)
    font_deco = _get_font(14)

    lines = []
    lines.append(('title', "📊 股市总览"))

    lines.append(('section', "📈 行情"))
    lines.append(('header', f"{'代码':<12} {'最新价':>10} {'涨跌幅':>10} {'趋势':>4}"))
    if market_data:
        for item in market_data:
            change = item['change']
            sign = '+' if change > 0 else ''
            trend_val = item.get('trend', 0)
            trend_arrow = '📈' if trend_val > 0 else ('📉' if trend_val < 0 else '➡️')
            color = UP_COLOR if change > 0 else (DOWN_COLOR if change < 0 else NEUTRAL_COLOR)
            line = f"{item['code']:<12} {item['price']:>10.2f} {sign}{change:>9.2f}% {trend_arrow:>4}"
            lines.append(('row', line, color))
    else:
        lines.append(('row', "暂无数据", NEUTRAL_COLOR))

    if holdings:
        lines.append(('section', "💼 我的持仓"))
        lines.append(('header', f"{'代码':<10} {'数量':>6} {'成本':>8} {'现价':>8} {'盈亏':>10}"))
        for h in holdings:
            profit = h.get('profit', 0)
            sign = '+' if profit > 0 else ''
            color = UP_COLOR if profit > 0 else (DOWN_COLOR if profit < 0 else NEUTRAL_COLOR)
            line = f"{h['code']:<10} {h['amount']:>6} {h['avg_cost']:>8.2f} {h['price']:>8.2f} {sign}{profit:>9.2f}"
            lines.append(('row', line, color))

    if news:
        lines.append(('section', "📰 市场新闻"))
        for n in news[:5]:
            content = n.get('content', n.get('title', ''))[:80]
            lines.append(('news', f"✦ {content}"))

    width = 800
    line_height = 30
    section_gap = 15
    title_height = 65
    height = title_height + len(lines) * line_height + len([l for l in lines if l[0] == 'section']) * section_gap + 50

    kline_imgs = []
    if kline_images:
        for code, img_buf in kline_images.items():
            try:
                img_buf.seek(0)
                img = Image.open(img_buf).convert('RGBA')
                ratio = (width - 80) / img.width
                new_h = int(img.height * ratio)
                img = img.resize((width - 80, new_h), Image.LANCZOS)
                kline_imgs.append((code, img))
                height += new_h + 40
            except Exception:
                pass

    height = max(height, 300)

    img = Image.new('RGBA', (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw animated blue-white gradient background
    _draw_bg_gradient(draw, width, height, BG_TOP, BG_BOTTOM)

    # Draw title bar decoration
    title_bar_y1 = 10
    title_bar_y2 = title_height + 10
    draw.rounded_rectangle(
        [(20, title_bar_y1), (width - 20, title_bar_y2)],
        radius=12, fill=(220, 238, 250, 180)
    )

    # Draw card body
    card_margin = 15
    card_x = card_margin
    card_y = title_height + 5
    card_w = width - card_margin * 2
    card_h = height - card_y - 10
    _draw_card(draw, card_x, card_y, card_w, card_h, radius=16)

    # Draw corner decorations on card
    _draw_corner_deco(draw, card_x + card_w, card_y + card_h, margin=28)

    y_pos = 28
    # Title with decorative stars
    draw.text((width // 2, y_pos), "✧ ✦", fill='#b8d4e8', font=font_deco, anchor='mm')
    draw.text((width // 2 + 90, y_pos), "✦ ✧", fill='#b8d4e8', font=font_deco, anchor='mm')
    draw.text((width // 2, y_pos + 6), "📊 股市总览", fill=TITLE_COLOR, font=font_title, anchor='mm')
    y_pos += title_height + 10

    for line_item in lines:
        if line_item[0] == 'section':
            y_pos += 5
            _draw_section_divider(draw, y_pos, 40, width - 40)
            y_pos += 8
            draw.text((40, y_pos), line_item[1], fill=SECTION_COLOR, font=font_section)
            y_pos += line_height + 2
        elif line_item[0] == 'header':
            draw.text((40, y_pos), line_item[1], fill=HEADER_COLOR, font=font_header)
            y_pos += line_height
        elif line_item[0] == 'row':
            text = line_item[1]
            color = line_item[2] if len(line_item) > 2 else TEXT_DARK
            draw.text((40, y_pos), text, fill=color, font=font_row)
            y_pos += line_height
        elif line_item[0] == 'news':
            draw.text((40, y_pos), line_item[1], fill=NEWS_COLOR, font=font_news)
            y_pos += line_height + 3

    for code, kline_img in kline_imgs:
        y_pos += 8
        # Cute label badge
        label_text = f"  {code} K线  "
        label_size = font_news.getbbox(label_text)
        label_w = label_size[2] - label_size[0] + 20
        label_h = 26
        label_x = 35
        draw.rounded_rectangle(
            [(label_x, y_pos), (label_x + label_w, y_pos + label_h)],
            radius=13, fill=(210, 233, 250, 220)
        )
        # Small decorative dots on badge
        draw.ellipse([(label_x + 6, y_pos + 9), (label_x + 10, y_pos + 13)], fill='#7ec8e3')
        draw.text((label_x + 14, y_pos + 3), label_text.strip(), fill=TITLE_COLOR, font=font_news)
        y_pos += label_h + 10
        # Paste K-line image with left padding
        img.paste(kline_img, (35, y_pos), kline_img)
        y_pos += kline_img.height + 15

    img_rgb = img.convert('RGB')
    buf = io.BytesIO()
    img_rgb.save(buf, format='png', quality=95)
    buf.seek(0)

    _save_cached_image(data_hash, buf)
    _clean_cache()

    buf.seek(0)
    return buf


def render_goods_market_image(goods_list, stock_data=None, currency_name="金币", currency_icon="💰"):
    data_hash = _compute_hash(str(goods_list), str(stock_data), currency_name, currency_icon)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    if not goods_list:
        return None

    # --- 布局参数 ---
    COLS = 3                          # 每行 3 个卡片
    CARD_IMG_SIZE = 150               # 正方形图片尺寸
    CARD_PADDING = 12
    CARD_INFO_HEIGHT = 58             # 图片下方信息区高度
    CARD_W = CARD_IMG_SIZE + CARD_PADDING * 2
    CARD_H = CARD_IMG_SIZE + CARD_INFO_HEIGHT + CARD_PADDING
    CARD_GAP = 16
    TITLE_HEIGHT = 70
    MARGIN_X = 24
    MARGIN_Y = 16

    rows = (len(goods_list) + COLS - 1) // COLS
    grid_w = COLS * CARD_W + (COLS - 1) * CARD_GAP
    WIDTH = grid_w + MARGIN_X * 2
    height = TITLE_HEIGHT + rows * (CARD_H + CARD_GAP) + MARGIN_Y * 2 + 20

    img = Image.new('RGBA', (WIDTH, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 背景渐变
    _draw_bg_gradient(draw, WIDTH, height, BG_GOODS_TOP, BG_GOODS_BOTTOM)

    # 标题栏
    draw.rounded_rectangle(
        [(20, 8), (WIDTH - 20, 58)],
        radius=14, fill=(220, 238, 250, 190)
    )
    font_title = _get_font(28, bold=True)
    draw.text((WIDTH // 2, 16), "📦 物资市场", fill=TITLE_COLOR, font=font_title, anchor='mt')
    deco_font = _get_font(11)
    draw.text((WIDTH // 2, 46), "— ✦  ·  ✦  ·  ✦ —", fill='#b8d4e8', font=deco_font, anchor='mt')

    # 字体
    font_name = _get_font(14, bold=True)
    font_price = _get_font(13)
    font_change = _get_font(12, bold=True)

    # 默认占位图（无图片时使用）
    def _make_placeholder(size):
        ph = Image.new('RGBA', (size, size), (230, 240, 250, 255))
        ph_draw = ImageDraw.Draw(ph)
        ph_draw.rounded_rectangle([(4, 4), (size - 4, size - 4)], radius=12,
                                  fill=(245, 250, 255, 255), outline=(190, 215, 240, 180), width=2)
        icon_font = _get_font(40)
        ph_draw.text((size // 2, size // 2 - 8), "📦", fill='#a0b8cc', font=icon_font, anchor='mm')
        no_img_font = _get_font(10)
        ph_draw.text((size // 2, size - 18), "暂无图片", fill='#b0c4d4', font=no_img_font, anchor='mm')
        return ph

    y_start = TITLE_HEIGHT + MARGIN_Y

    for idx, g in enumerate(goods_list):
        col = idx % COLS
        row = idx // COLS
        card_x = MARGIN_X + col * (CARD_W + CARD_GAP)
        card_y = y_start + row * (CARD_H + CARD_GAP)

        # 卡片背景
        _draw_card(draw, card_x, card_y, CARD_W, CARD_H, radius=14)

        # 正方形商品图
        img_x = card_x + CARD_PADDING
        img_y = card_y + CARD_PADDING
        img_rect = [(img_x, img_y), (img_x + CARD_IMG_SIZE, img_y + CARD_IMG_SIZE)]

        preview_path = g.get('preview_image', '')
        goods_img = None
        if preview_path and os.path.exists(preview_path):
            try:
                goods_img = Image.open(preview_path).convert('RGBA')
                # 居中裁剪为正方形
                w, h = goods_img.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                goods_img = goods_img.crop((left, top, left + side, top + side))
                goods_img = goods_img.resize((CARD_IMG_SIZE, CARD_IMG_SIZE), Image.LANCZOS)
                # 圆角遮罩
                mask = Image.new('L', (CARD_IMG_SIZE, CARD_IMG_SIZE), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle([(0, 0), (CARD_IMG_SIZE, CARD_IMG_SIZE)],
                                            radius=10, fill=255)
                img.paste(goods_img, (img_x, img_y), mask)
            except Exception:
                goods_img = None

        if goods_img is None:
            placeholder = _make_placeholder(CARD_IMG_SIZE)
            mask = Image.new('L', (CARD_IMG_SIZE, CARD_IMG_SIZE), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (CARD_IMG_SIZE, CARD_IMG_SIZE)],
                                        radius=10, fill=255)
            img.paste(placeholder, (img_x, img_y), mask)

        # 图片下方信息区
        info_y = img_y + CARD_IMG_SIZE + 8
        center_x = card_x + CARD_W // 2

        # 物资名称
        name = g.get('name', g.get('goods_id', ''))
        draw.text((center_x, info_y), name, fill=TEXT_DARK, font=font_name, anchor='mt')

        # 价格
        price_text = f"{currency_icon}{g['current_price']:.2f}"
        draw.text((center_x, info_y + 20), price_text, fill=TEXT_DARK, font=font_price, anchor='mt')

        # 相对基准价涨跌幅
        base_price = g.get('base_price', 0)
        if base_price and base_price > 0:
            base_change = (g['current_price'] - base_price) / base_price * 100
        else:
            base_change = 0
        sign = '+' if base_change > 0 else ''
        change_color = UP_COLOR if base_change > 0 else (DOWN_COLOR if base_change < 0 else NEUTRAL_COLOR)
        change_text = f"基准价 {sign}{base_change:.1f}%"
        draw.text((center_x, info_y + 38), change_text, fill=change_color, font=font_change, anchor='mt')

    img_rgb = img.convert('RGB')
    buf = io.BytesIO()
    img_rgb.save(buf, format='png', quality=95)
    buf.seek(0)

    _save_cached_image(data_hash, buf)
    _clean_cache()

    buf.seek(0)
    return buf


def render_rank_image(rank_data, currency_name="金币", currency_icon="💰"):
    data_hash = _compute_hash(str(rank_data), currency_name, currency_icon)
    cached = _get_cached_image(data_hash)
    if cached:
        with open(cached, 'rb') as f:
            return io.BytesIO(f.read())

    # --- 色彩常量 ---
    GOLD = '#FFD700'
    GOLD_DARK = '#B8860B'
    GOLD_BG = (255, 248, 220, 200)
    GOLD_BORDER = (255, 200, 50, 220)
    GOLD_GLOW = (255, 215, 0, 50)

    SILVER = '#C0C0C0'
    SILVER_DARK = '#808080'
    SILVER_BG = (240, 244, 248, 200)
    SILVER_BORDER = (180, 195, 210, 220)

    BRONZE = '#CD7F32'
    BRONZE_DARK = '#8B5A2B'
    BRONZE_BG = (255, 240, 225, 200)
    BRONZE_BORDER = (210, 160, 100, 220)

    PODIUM_COLORS = [
        {'medal': '🥇', 'accent': GOLD, 'accent_dark': GOLD_DARK,
         'bg': GOLD_BG, 'border': GOLD_BORDER, 'glow': GOLD_GLOW, 'bar': '#FFD700'},
        {'medal': '🥈', 'accent': SILVER, 'accent_dark': SILVER_DARK,
         'bg': SILVER_BG, 'border': SILVER_BORDER, 'glow': (192, 192, 192, 40), 'bar': '#C0C0C0'},
        {'medal': '🥉', 'accent': BRONZE, 'accent_dark': BRONZE_DARK,
         'bg': BRONZE_BG, 'border': BRONZE_BORDER, 'glow': (205, 127, 50, 40), 'bar': '#CD7F32'},
    ]

    TOP3_HEIGHT = 90       # TOP1-3 每行高度
    NORMAL_HEIGHT = 38     # TOP4-20 每行高度
    TITLE_HEIGHT = 70
    WIDTH = 600
    TOP3_COUNT = min(3, len(rank_data))
    NORMAL_COUNT = max(0, min(20, len(rank_data)) - TOP3_COUNT)

    body_height = TOP3_COUNT * TOP3_HEIGHT + NORMAL_COUNT * NORMAL_HEIGHT + 30
    height = TITLE_HEIGHT + body_height + 40

    img = Image.new('RGBA', (WIDTH, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 背景渐变
    _draw_bg_gradient(draw, WIDTH, height, BG_RANK_TOP, BG_RANK_BOTTOM)

    # 标题栏
    draw.rounded_rectangle(
        [(20, 8), (WIDTH - 20, 58)],
        radius=14, fill=(215, 232, 248, 190)
    )
    font_title = _get_font(30, bold=True)
    draw.text((WIDTH // 2, 18), "🏆 财富排行榜", fill=TITLE_COLOR, font=font_title, anchor='mt')
    deco_font = _get_font(11)
    draw.text((WIDTH // 2, 48), "— ✦  ·  ✦  ·  ✦ —", fill='#b8d4e8', font=deco_font, anchor='mt')

    y = TITLE_HEIGHT + 10

    # ===== TOP 1-3 领奖台风格 =====
    for i in range(TOP3_COUNT):
        r = rank_data[i]
        pc = PODIUM_COLORS[i]

        # 外发光
        for g_offset in range(6, 0, -1):
            draw.rounded_rectangle(
                [(24 - g_offset, y - g_offset), (WIDTH - 24 + g_offset, y + TOP3_HEIGHT + g_offset)],
                radius=18, fill=pc['glow']
            )

        # 卡片背景
        draw.rounded_rectangle(
            [(24, y), (WIDTH - 24, y + TOP3_HEIGHT)],
            radius=16, fill=pc['bg'], outline=pc['border'], width=2
        )

        # 左侧奖牌色竖条
        draw.rounded_rectangle(
            [(24, y), (30, y + TOP3_HEIGHT)],
            radius=4, fill=pc['border']
        )

        # 排名徽章
        badge_size = 48 if i == 0 else 42
        badge_x = 50
        badge_y = y + (TOP3_HEIGHT - badge_size) // 2
        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + badge_size, badge_y + badge_size)],
            radius=badge_size // 2, fill=pc['border']
        )
        # 徽章内圆
        inner_margin = 3
        draw.rounded_rectangle(
            [(badge_x + inner_margin, badge_y + inner_margin),
             (badge_x + badge_size - inner_margin, badge_y + badge_size - inner_margin)],
            radius=(badge_size - inner_margin * 2) // 2, fill=(255, 255, 255, 230)
        )
        badge_font = _get_font(22 if i == 0 else 20, bold=True)
        draw.text((badge_x + badge_size // 2, badge_y + badge_size // 2),
                  str(i + 1), fill=pc['accent_dark'], font=badge_font, anchor='mm')

        # 用户名
        name_x = badge_x + badge_size + 18
        name_font = _get_font(22 if i == 0 else 20, bold=True)
        draw.text((name_x, y + 14), r['user_name'], fill=pc['accent_dark'], font=name_font)

        # 财富金额
        wealth_font = _get_font(18 if i == 0 else 16, bold=True)
        wealth_text = f"{currency_icon} {r['total_wealth']:.2f} {currency_name}"
        draw.text((name_x, y + TOP3_HEIGHT - 28), wealth_text, fill=TEXT_DARK, font=wealth_font)

        # 右侧奖牌图标
        medal_font = _get_font(32 if i == 0 else 28)
        draw.text((WIDTH - 60, y + TOP3_HEIGHT // 2), pc['medal'],
                  fill=pc['accent'], font=medal_font, anchor='mm')

        # TOP1 特殊：王冠装饰线
        if i == 0:
            draw.text((WIDTH // 2, y - 2), "👑", fill=GOLD, font=_get_font(16), anchor='mb')

        y += TOP3_HEIGHT + 6

    # ===== TOP 4-20 简洁列表 =====
    if NORMAL_COUNT > 0:
        # 分隔线
        _draw_section_divider(draw, y + 6, 40, WIDTH - 40)
        y += 18

        # 列表头
        header_font = _get_font(13, bold=True)
        draw.text((70, y), "排名", fill=HEADER_COLOR, font=header_font)
        draw.text((140, y), "用户", fill=HEADER_COLOR, font=header_font)
        draw.text((WIDTH - 50, y), "财富", fill=HEADER_COLOR, font=header_font, anchor='rt')
        y += 22

        row_font = _get_font(15)
        for j in range(NORMAL_COUNT):
            rank_idx = TOP3_COUNT + j
            r = rank_data[rank_idx]
            rank_num = rank_idx + 1

            # 偶数行浅色背景
            if j % 2 == 0:
                draw.rounded_rectangle(
                    [(30, y - 2), (WIDTH - 30, y + NORMAL_HEIGHT - 4)],
                    radius=8, fill=(240, 247, 255, 100)
                )

            # 排名数字
            num_font = _get_font(15, bold=True)
            draw.text((80, y + NORMAL_HEIGHT // 2 - 4), str(rank_num),
                      fill=TEXT_MUTED, font=num_font, anchor='mm')

            # 用户名
            draw.text((140, y + 6), r['user_name'], fill=TEXT_DARK, font=row_font)

            # 财富
            wealth_text = f"{r['total_wealth']:.2f}"
            draw.text((WIDTH - 50, y + 6), wealth_text, fill=TEXT_MUTED, font=row_font, anchor='rt')

            y += NORMAL_HEIGHT

    img_rgb = img.convert('RGB')
    buf = io.BytesIO()
    img_rgb.save(buf, format='png', quality=95)
    buf.seek(0)

    _save_cached_image(data_hash, buf)
    _clean_cache()

    buf.seek(0)
    return buf

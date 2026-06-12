"""FinCenter 图片渲染模块

使用 AstrBot 框架内置的 html_render 将 HTML+Jinja2 模板渲染为图片。
所有渲染函数返回 (html_template_str, jinja2_data_dict) 元组，
由 handler 调用 self.html_render(html, data, options=options) 完成截图。
K线图使用 ECharts 专业金融图表库（CDN 加载）。
"""
import os
import logging

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_assets_dir = os.path.join(_base_dir, 'assets')
_templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')

# Jinja2 环境
_jinja_env = None


def set_paths(base_dir: str = None, assets_dir: str = None, data_dir: str = None):
    global _base_dir, _assets_dir, _templates_dir, _jinja_env
    if base_dir:
        _base_dir = base_dir
        _assets_dir = os.path.join(_base_dir, 'assets')
    if assets_dir:
        _assets_dir = assets_dir
    _templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
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


# ===== 渲染函数 =====
# 所有函数返回 (html_content_str, data_dict) 元组
# handler 调用: url = await html_render(html_content, data, options=options)

def render_kline_html(history_list, title="K线走势", tech_levels=None, max_candles=50, font_key=None):
    """生成 K 线图 HTML

    Args:
        history_list: 历史K线数据列表，每项包含 date/open/high/low/close/volume
        title: 图表标题
        tech_levels: 技术指标，包含 ma5/ma20/support/resistance
        max_candles: 最大K线数量
        font_key: 字体键（保留兼容，暂不使用）

    Returns:
        (html_content, data_dict) 元组，无数据时返回 None
    """
    if not history_list:
        return None

    candles = history_list[-max_candles:] if len(history_list) > max_candles else history_list

    # 准备 ECharts 数据
    dates = []
    ohlc = []
    volumes = []
    ma5_data = []
    ma20_data = []

    for c in candles:
        dates.append(str(c['date']))
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

    # 检查本地 ECharts 文件
    echarts_path = os.path.join(_assets_dir, 'js', 'echarts.min.js')
    if os.path.exists(echarts_path):
        echarts_src = 'file:///' + os.path.abspath(echarts_path).replace('\\', '/')
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

    # html_render 签名: html_render(html, data, options=options)
    # data 已内嵌在 HTML 中，传空 dict
    return (html_content, {})


def render_stock_market_html(market_data, holdings=None, news=None,
                              currency_name="金币", currency_icon="💰",
                              kline_html_list=None, font_key=None):
    """生成股市总览 HTML

    Args:
        market_data: 行情数据列表
        holdings: 持仓数据列表
        news: 新闻数据列表
        currency_name: 货币名称
        currency_icon: 货币图标
        kline_html_list: K线图 HTML 列表（已渲染的 HTML 片段）
        font_key: 字体键（保留兼容）

    Returns:
        (html_content, data_dict) 元组
    """
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
        kline_images={},  # 不再使用 base64 内嵌，K线图单独渲染
        currency_name=currency_name,
        currency_icon=currency_icon,
    )

    return (html_content, {})


def render_goods_market_html(goods_list, stock_data=None,
                              currency_name="金币", currency_icon="💰"):
    """生成物资市场 HTML

    Args:
        goods_list: 物资列表
        stock_data: 背包库存数据
        currency_name: 货币名称
        currency_icon: 货币图标

    Returns:
        (html_content, data_dict) 元组，无数据时返回 None
    """
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

    return (html_content, {})


def render_rank_html(rank_data, currency_name="金币", currency_icon="💰"):
    """生成财富排行榜 HTML

    Args:
        rank_data: 排行数据列表，每项包含 user_name/total_wealth
        currency_name: 货币名称
        currency_icon: 货币图标

    Returns:
        (html_content, data_dict) 元组
    """
    env = _get_jinja()
    template = env.get_template('rank.html')
    html_content = template.render(
        rank_data=rank_data,
        currency_name=currency_name,
        currency_icon=currency_icon,
    )

    return (html_content, {})


def render_help_html(title, sections, tips=None, quick_ref=None,
                     currency_name="金币", currency_icon="💰"):
    """生成帮助页 HTML

    Args:
        title: 帮助页标题
        sections: 分组列表，每项包含 section_name 和 commands
        tips: 底部提示文字列表
        quick_ref: 子菜单快捷入口
        currency_name: 货币名称
        currency_icon: 货币图标

    Returns:
        (html_content, data_dict) 元组
    """
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

    return (html_content, {})


async def shutdown():
    """清理资源（兼容旧接口，现在无需手动关闭浏览器）"""
    pass

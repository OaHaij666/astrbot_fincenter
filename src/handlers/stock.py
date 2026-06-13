"""股市处理器

处理股市查看、买卖、K线图、新闻等指令。
图片渲染对齐参考项目: html_render → 文件路径 → event.image_result(文件路径)
"""
import asyncio
import base64
import os

from astrbot.api import logger
from ..core.database import StockHistory, get_china_time
from ..utils import plotter


class StockHandler:
    def __init__(self, plugin, html_render):
        self.plugin = plugin

    async def _build_market_image(self, group_id, user_id):
        if not self.plugin.stock_market:
            return None

        snapshot = self.plugin.stock_market.get_price_snapshot()
        codes = list(snapshot.keys())

        prev_prices = {}
        with self.plugin.db.session_scope() as session:
            for code in codes:
                history = session.query(StockHistory).filter_by(
                    group_id=group_id, code=code
                ).order_by(StockHistory.timestamp.desc()).limit(2).all()
                if len(history) >= 2:
                    prev_prices[code] = history[1].close

        market_data = []
        for code, snap in snapshot.items():
            price = float(snap["price"])
            prev = float(prev_prices.get(code, price))
            change = ((price - prev) / prev * 100) if prev > 0 else 0
            market_data.append({
                'code': code,
                'price': price,
                'change': change,
                'trend': snap["trend"],
            })

        holdings_data = self.plugin.stock_market.get_holdings(group_id, user_id)

        news_list = self.plugin.stock_market.get_today_news(group_id)
        news_data = []
        for n in news_list:
            news_data.append({
                'event_type': n['event_type'],
                'content': n['content'],
                'time': n['timestamp'].strftime("%H:%M") if n.get('timestamp') else "",
            })

        # 生成每只股票的 K 线 base64 图片
        kline_images = {}
        for code in codes:
            kline_b64 = await self._generate_kline_base64(code, group_id)
            if kline_b64:
                kline_images[code] = kline_b64

        result = plotter.render_stock_market_html(
            market_data, holdings_data, news_data,
            self.plugin.config.currency.currency_name,
            self.plugin.config.currency.currency_icon,
            kline_html_list=kline_images,
        )
        if not result:
            return None

        html_content, data = result
        url = await self.plugin._render_image(html_content, data)
        return url

    async def _generate_kline_base64(self, code, group_id, limit=30):
        """生成单只股票 K 线的 base64 图片字符串"""
        with self.plugin.db.session_scope() as session:
            history = session.query(StockHistory).filter_by(
                group_id=group_id, code=code
            ).order_by(StockHistory.timestamp.desc()).limit(limit).all()
            history_dicts = [h.to_kline_dict() for h in reversed(history)]

        if not history_dicts:
            return None

        tech_levels = self.plugin.stock_market.get_tech_levels(code)
        result = plotter.render_kline_html(
            history_dicts, title=f"{code} K线走势",
            tech_levels=tech_levels,
            max_candles=self.plugin.config.stock.stock_kline_candles,
            font_key=self.plugin.config.stock.stock_font,
        )
        if not result:
            return None

        html_content, data = result
        image_path = await self.plugin._render_image(html_content, data)
        if not image_path:
            return None

        try:
            with open(image_path, "rb") as f:
                img_bytes = f.read()
            return base64.b64encode(img_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"读取 K 线图片失败 {code}: {e}")
            return None
        finally:
            try:
                os.unlink(image_path)
            except Exception:
                pass

    async def _build_kline_image(self, code, limit, group_id):
        with self.plugin.db.session_scope() as session:
            history = session.query(StockHistory).filter_by(
                group_id=group_id, code=code
            ).order_by(StockHistory.timestamp.desc()).limit(limit).all()
            history_dicts = [h.to_kline_dict() for h in reversed(history)]

        if not history_dicts:
            return None

        tech_levels = self.plugin.stock_market.get_tech_levels(code)
        result = plotter.render_kline_html(
            history_dicts, title=f"{code} K线走势",
            tech_levels=tech_levels,
            max_candles=self.plugin.config.stock.stock_kline_candles,
            font_key=self.plugin.config.stock.stock_font,
        )
        if not result:
            return None

        html_content, data = result
        url = await self.plugin._render_image(html_content, data)
        return url

    async def handle(self, event, args, group_id, user_id, user_name):
        if not self.plugin.stock_market:
            yield event.plain_result("股市模块未启用")
            return

        sub = args[2] if len(args) >= 3 else None

        if sub is None:
            result = plotter.render_help_html(
                title="📈 股市指令",
                sections=[{
                    'commands': [
                        {'cmd': '/fc stock market', 'desc': '股市总览（行情+持仓+K线+新闻）'},
                        {'cmd': '/fc stock buy <代码> <数量>', 'desc': '买入股票'},
                        {'cmd': '/fc stock sell <代码> <数量>', 'desc': '卖出股票'},
                        {'cmd': '/fc stock assets', 'desc': '查看我的持仓'},
                        {'cmd': '/fc stock kline <代码> [条数]', 'desc': '查看K线图（默认60条）'},
                        {'cmd': '/fc stock news', 'desc': '查看市场新闻'},
                        {'cmd': '/fc stock event [代码]', 'desc': '手动触发市场事件', 'admin': True},
                    ],
                }],
                tips=[f'代码列表请先查看 /fc stock market，买入前建议先看K线'],
            )
            if result:
                html_content, data = result
                image_path = await self.plugin._render_image(html_content, data)
                if image_path:
                    yield event.image_result(image_path)
                    return
            yield event.plain_result(self._get_stock_help_text())
            return

        sub = args[2]

        if sub == "market":
            image_path = await self._build_market_image(group_id, user_id)
            if image_path:
                yield event.image_result(image_path)
                return
            # 文字回退
            status = self.plugin.stock_market.get_market_status()
            yield event.plain_result(status)

        elif sub == "buy":
            if len(args) < 5:
                yield event.plain_result("格式: /fc stock buy <代码> <数量>")
                return
            code = args[3].upper()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self.plugin.stock_market.execute_buy, group_id, user_id, code, args[4]
            )
            yield event.plain_result(result["msg"])

        elif sub == "sell":
            if len(args) < 5:
                yield event.plain_result("格式: /fc stock sell <代码> <数量>")
                return
            code = args[3].upper()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self.plugin.stock_market.execute_sell, group_id, user_id, code, args[4]
            )
            yield event.plain_result(result["msg"])

        elif sub == "assets":
            holdings = self.plugin.stock_market.get_holdings(group_id, user_id)
            if not holdings:
                yield event.plain_result("暂无持仓")
                return

            # 图片优先
            result = plotter.render_stock_assets_html(
                user_name, holdings,
                self.plugin.config.currency.currency_name,
                self.plugin.config.currency.currency_icon,
            )
            if result:
                html_content, data = result
                image_path = await self.plugin._render_image(html_content, data)
                if image_path:
                    yield event.image_result(image_path)
                    return

            # 文字回退
            msg = f"📈 {user_name} 的股票持仓\n━━━━━━━━━━━━━━\n"
            total_value = 0
            total_profit = 0
            for h in holdings:
                profit_sign = "+" if h['profit'] >= 0 else ""
                msg += f"{h['code']}: {h['amount']:.2f}股\n  成本{h['avg_cost']:.2f} → 现价{h['current_price']:.2f}\n  市值{h['market_value']:.2f} ({profit_sign}{h['profit_pct']:.1f}%)\n"
                total_value += h['market_value']
                total_profit += h['profit']

            profit_sign = "+" if total_profit >= 0 else ""
            msg += f"\n📊 总市值: {total_value:.2f}\n📊 总盈亏: {profit_sign}{total_profit:.2f}"
            yield event.plain_result(msg)

        elif sub == "kline":
            if len(args) < 4:
                yield event.plain_result("格式: /fc stock kline <代码> [条数]")
                return
            code = args[3].upper()
            if code not in self.plugin.stock_market.prices:
                yield event.plain_result(f"股票代码 {code} 不存在")
                return

            limit = self.plugin.config.stock.stock_kline_candles
            if len(args) >= 5:
                try:
                    limit = int(args[4])
                    limit = max(10, min(200, limit))
                except ValueError:
                    pass

            image_path = await self._build_kline_image(code, limit, group_id)
            if image_path:
                yield event.image_result(image_path)
                return
            # 文字回退
            with self.plugin.db.session_scope() as session:
                history = session.query(StockHistory).filter_by(
                    group_id=group_id, code=code
                ).order_by(StockHistory.timestamp.desc()).limit(10).all()
            if history:
                lines = [f"📊 {code} 近期走势", "━━━━━━━━━━━━━━"]
                for h in reversed(history):
                    lines.append(f"{h.timestamp}: 开{h.open:.2f} 高{h.high:.2f} 低{h.low:.2f} 收{h.close:.2f}")
                yield event.plain_result("\n".join(lines))
            else:
                yield event.plain_result(f"暂无 {code} 的历史数据")

        elif sub == "news":
            news_list = self.plugin.stock_market.get_today_news(group_id)
            if not news_list:
                yield event.plain_result("今日暂无市场新闻")
                return

            # 图片优先
            result = plotter.render_stock_news_html(
                news_list,
                self.plugin.config.currency.currency_name,
                self.plugin.config.currency.currency_icon,
            )
            if result:
                html_content, data = result
                image_path = await self.plugin._render_image(html_content, data)
                if image_path:
                    yield event.image_result(image_path)
                    return

            # 文字回退
            now = get_china_time()
            msg = f"📰 今日市场快讯 ({now.strftime('%m-%d')})\n━━━━━━━━━━━━━━\n"
            for n in news_list:
                t_str = n['timestamp'].strftime("%H:%M") if n.get('timestamp') else ""
                event_icon = {"major_positive": "🚀", "positive": "📈", "slight_positive": "↗",
                              "neutral": "➡️", "slight_negative": "↘", "negative": "📉",
                              "major_negative": "💥", "volatility": "⚠️"}.get(n['event_type'], "📰")
                msg += f"[{t_str}] {event_icon} {n['content']}\n"
            yield event.plain_result(msg)

        elif sub == "event":
            if str(user_id) not in self.plugin.config.basic.admin_ids:
                yield event.plain_result("仅限管理员使用")
                return
            target_code = args[3].upper() if len(args) >= 4 else None
            if target_code and target_code not in self.plugin.stock_market.prices:
                yield event.plain_result(f"股票代码 {target_code} 不存在")
                return
            news_result = self.plugin.stock_market.trigger_news(target_code)
            if not news_result:
                yield event.plain_result("事件生成失败")
                return
            event_icon = {"major_positive": "🚀", "positive": "📈", "slight_positive": "↗",
                          "neutral": "➡️", "slight_negative": "↘", "negative": "📉",
                          "major_negative": "💥", "volatility": "⚠️"}.get(news_result["event_type"], "📰")
            msg = f"{event_icon} 市场事件触发！\n"
            msg += f"公司：{news_result['name']}（{news_result['code']}）\n"
            msg += f"内容：{news_result['content']}\n"
            if news_result.get("broadcast"):
                yield event.plain_result(msg)
            else:
                msg += "\n（事件已记录，未广播）"
                yield event.plain_result(msg)

        else:
            yield event.plain_result("未知股市指令")

    def _get_stock_help_text(self):
        lines = [
            "📈 股市指令",
            "━━━━━━━━━━━━━━",
            "  /fc stock market          股市总览(行情+持仓+K线+新闻)",
            "  /fc stock buy <代码> <数量>  买入",
            "  /fc stock sell <代码> <数量> 卖出",
            "  /fc stock assets          我的持仓",
            "  /fc stock kline <代码> [条数]  K线图(默认60条)",
            "  /fc stock news            市场新闻",
            "  /fc stock event [代码]     手动触发市场事件(管理员)",
        ]
        return "\n".join(lines)

"""物资市场处理器

处理物资市场查看、买卖、背包查看等指令。
图片渲染对齐参考项目: html_render → 文件路径 → event.image_result(文件路径)
"""
import os

from astrbot.api import logger
from ..utils import plotter


class GoodsHandler:
    def __init__(self, plugin, html_render):
        self.plugin = plugin

    async def handle(self, event, args, group_id, user_id, user_name):
        if not self.plugin.goods_market:
            yield event.plain_result("物资市场模块未启用")
            return

        sub = args[2] if len(args) >= 3 else None

        if sub is None:
            result = plotter.render_help_html(
                title="📦 物资指令",
                sections=[{
                    'commands': [
                        {'cmd': '/fc goods market', 'desc': '物资市场总览（图文卡片）'},
                        {'cmd': '/fc goods buy <ID> <数量>', 'desc': '买入物资'},
                        {'cmd': '/fc goods sell <ID> <数量>', 'desc': '卖出物资'},
                        {'cmd': '/fc goods backpack', 'desc': '查看我的背包'},
                    ],
                }],
                tips=['物资价格会定期刷新，请注意市场波动'],
            )
            if result:
                html_content, data = result
                image_path = await self.plugin._render_image(html_content, data)
                if image_path:
                    yield event.image_result(image_path)
                    return
            yield event.plain_result(self._get_goods_help_text())
            return

        sub = args[2]

        if sub == "market":
            goods_list = self.plugin.goods_market.get_market_list(group_id)
            backpack = self.plugin.goods_market.get_backpack(group_id, user_id)
            stock_data = {b['goods_id']: b['amount'] for b in backpack}

            result = plotter.render_goods_market_html(
                goods_list, stock_data,
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
            currency_icon = self.plugin.config.currency.currency_icon
            lines = ["📦 物资市场", "━━━━━━━━━━━━━━"]
            for g in goods_list:
                change_sign = "+" if g['change_pct'] >= 0 else ""
                lines.append(f"{g['icon']} {g['name']}: {currency_icon}{g['current_price']:.2f} ({change_sign}{g['change_pct']:.1f}%)")
            yield event.plain_result("\n".join(lines))

        elif sub == "buy":
            if len(args) < 5:
                yield event.plain_result("格式: /fc goods buy <物资ID> <数量>")
                return
            goods_id = args[3]
            result = self.plugin.goods_market.buy_goods(group_id, user_id, goods_id, args[4])
            yield event.plain_result(result["msg"])

        elif sub == "sell":
            if len(args) < 5:
                yield event.plain_result("格式: /fc goods sell <物资ID> <数量>")
                return
            goods_id = args[3]
            result = self.plugin.goods_market.sell_goods(group_id, user_id, goods_id, args[4])
            yield event.plain_result(result["msg"])

        elif sub == "backpack":
            backpack = self.plugin.goods_market.get_backpack(group_id, user_id)
            if not backpack:
                yield event.plain_result("背包空空如也")
                return

            # 图片优先
            result = plotter.render_goods_backpack_html(
                user_name, backpack,
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
            currency_icon = self.plugin.config.currency.currency_icon
            msg = f"🎒 {user_name} 的物资背包\n━━━━━━━━━━━━━━\n"
            total_value = 0
            for b in backpack:
                msg += f"{b['icon']} {b['name']}: {b['amount']:.2f} (单价{b['current_price']:.2f}, 市值{b['total_value']:.2f})\n"
                total_value += b['total_value']
            msg += f"\n📦 总市值: {currency_icon}{total_value:.2f}"
            yield event.plain_result(msg)

        else:
            yield event.plain_result("未知物资指令")

    def _get_goods_help_text(self):
        lines = [
            "📦 物资指令",
            "━━━━━━━━━━━━━━",
            "  /fc goods market          物资市场总览",
            "  /fc goods buy <ID> <数量>   买入物资",
            "  /fc goods sell <ID> <数量>  卖出物资",
            "  /fc goods backpack        我的背包",
        ]
        return "\n".join(lines)

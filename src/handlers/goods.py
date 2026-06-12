"""物资市场处理器

处理物资市场查看、买卖、背包查看等指令。
图片渲染对齐参考项目: html_render(html_content, data_dict, return_url=False, options)
"""
import base64

from astrbot.api import logger
from ..utils import plotter


class GoodsHandler:
    def __init__(self, plugin, html_render):
        self.plugin = plugin
        self.html_render = html_render

    async def _render_image(self, html_content, data=None, options=None):
        """调用框架 html_render 渲染 HTML 为图片，返回可用于 event.image_result() 的 URL

        对齐参考项目: html_render(html_content, data_dict, return_url=False, options)
        return_url=False 时返回 bytes 或 str(文件路径)
        bytes → base64:// URL, str → 直接作为 URL
        """
        try:
            image_data = await self.html_render(
                html_content,
                data or {},
                False,  # return_url=False，直接获取图片数据
                options or {"type": "png"},
            )
            if not image_data:
                return None

            if isinstance(image_data, bytes):
                b64 = base64.b64encode(image_data).decode("utf-8")
                return f"base64://{b64}"
            elif isinstance(image_data, str):
                return image_data
            else:
                logger.warning(f"html_render 返回了意外类型: {type(image_data)}")
                return None
        except Exception as e:
            logger.error(f"html_render failed: {e}")
            return None

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
                url = await self._render_image(html_content, data)
                if url:
                    yield event.image_result(url)
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
                url = await self._render_image(html_content, data)
                if url:
                    yield event.image_result(url)
                else:
                    yield event.plain_result("图片生成失败")
            else:
                yield event.plain_result("图片生成失败")

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

            msg = f"🎒 {user_name} 的物资背包\n━━━━━━━━━━━━━━\n"
            total_value = 0
            for b in backpack:
                msg += f"{b['icon']} {b['name']}: {b['amount']:.2f} (单价{b['current_price']:.2f}, 市值{b['total_value']:.2f})\n"
                total_value += b['total_value']
            msg += f"\n📦 总市值: {total_value:.2f}"
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

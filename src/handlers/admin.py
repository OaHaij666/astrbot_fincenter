"""管理员处理器

处理余额管理、股市控制、物资管理等管理员指令。
排行榜已移至普通用户指令，此处仅保留管理员入口。
所有数据库操作通过 session_scope() 上下文管理器进行。
图片渲染对齐参考项目: html_render(html_content, data_dict, return_url=False, options)
"""
import base64
import os

from astrbot.api import logger
from ..core.database import UserAccount, GoodsDefinition, GoodsMarketPrice
from ..utils import plotter


class AdminHandler:
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
                # str 可能是文件路径，读取后转 base64（对齐参考项目）
                if os.path.isfile(image_data):
                    with open(image_data, "rb") as f:
                        file_data = f.read()
                    b64 = base64.b64encode(file_data).decode("utf-8")
                    return f"base64://{b64}"
                return image_data
            else:
                logger.warning(f"html_render 返回了意外类型: {type(image_data)}")
                return None
        except Exception as e:
            logger.error(f"html_render failed: {e}")
            return None

    async def handle(self, event, args, group_id, user_id, user_name):
        if str(user_id) not in self.plugin.config.basic.admin_ids:
            yield event.plain_result("仅限管理员使用")
            return

        sub = args[2] if len(args) >= 3 else None

        if sub is None:
            result = plotter.render_help_html(
                title="⚙️ 管理员指令",
                sections=[
                    {
                        'section_name': '💰 余额管理',
                        'commands': [
                            {'cmd': '/fc admin balance <@> <金额>', 'desc': '为用户增减余额'},
                            {'cmd': '/fc admin setbalance <@> <金额>', 'desc': '直接设置用户余额'},
                        ],
                    },
                    {
                        'section_name': '📈 股市控制',
                        'commands': [
                            {'cmd': '/fc admin stock open', 'desc': '强制开市'},
                            {'cmd': '/fc admin stock close', 'desc': '强制休市'},
                            {'cmd': '/fc admin stock auto', 'desc': '恢复自动模式'},
                        ],
                    },
                    {
                        'section_name': '📦 物资管理',
                        'commands': [
                            {'cmd': '/fc admin goods add <ID> <名称> <价>', 'desc': '添加物资'},
                            {'cmd': '/fc admin goods remove <物资ID>', 'desc': '移除物资'},
                            {'cmd': '/fc admin goods setprice <ID> <价>', 'desc': '设置价格'},
                            {'cmd': '/fc admin goods setvolatility <ID> <率>', 'desc': '设置波动率'},
                            {'cmd': '/fc admin goods reset', 'desc': '重置所有物资价格至基准价'},
                        ],
                    },
                ],
                tips=['上述指令仅限管理员使用，@用户 可直接用 QQ号'],
            )
            if result:
                html_content, data = result
                url = await self._render_image(html_content, data)
                if url:
                    yield event.image_result(url)
                    return
            yield event.plain_result(self._get_admin_help_text())
            return

        sub = args[2]
        currency_name = self.plugin.config.currency.currency_name

        if sub == "balance":
            if len(args) < 5:
                yield event.plain_result("格式: /fc admin balance <@用户> <金额>")
                return
            target_id = None
            mentions = event.message_obj.message
            for seg in mentions:
                if hasattr(seg, 'type') and seg.type == 'at':
                    target_id = seg.data.get('qq', '')
                    break
            if not target_id:
                target_id = args[3]

            try:
                amount = float(args[4])
            except ValueError:
                yield event.plain_result("金额必须是数字")
                return

            with self.plugin.db.session_scope() as session:
                user = session.query(UserAccount).filter_by(
                    group_id=group_id, user_id=str(target_id)
                ).first()
                if not user:
                    yield event.plain_result("目标用户不存在")
                    return

                user.add_balance(amount)
                if amount > 0:
                    user.add_earned(amount)

            yield event.plain_result(
                f"✅ 已为 {target_id} {'增加' if amount > 0 else '减少'} "
                f"{abs(amount):.2f} {currency_name}"
            )

        elif sub == "setbalance":
            if len(args) < 5:
                yield event.plain_result("格式: /fc admin setbalance <@用户> <金额>")
                return
            target_id = None
            mentions = event.message_obj.message
            for seg in mentions:
                if hasattr(seg, 'type') and seg.type == 'at':
                    target_id = seg.data.get('qq', '')
                    break
            if not target_id:
                target_id = args[3]

            try:
                amount = float(args[4])
            except ValueError:
                yield event.plain_result("金额必须是数字")
                return

            with self.plugin.db.session_scope() as session:
                user = session.query(UserAccount).filter_by(
                    group_id=group_id, user_id=str(target_id)
                ).first()
                if not user:
                    yield event.plain_result("目标用户不存在")
                    return

                user.balance = amount
                if user.balance < 0:
                    user.balance = 0

            yield event.plain_result(f"✅ 已将 {target_id} 的余额设为 {amount:.2f}")

        elif sub == "stock":
            if not self.plugin.stock_market:
                yield event.plain_result("股市模块未启用")
                return

            action = args[3] if len(args) >= 4 else None
            if action == "open":
                self.plugin.stock_market.set_open(True)
                yield event.plain_result("✅ 股市已强制开市")
            elif action == "close":
                self.plugin.stock_market.set_open(False)
                yield event.plain_result("✅ 股市已强制休市")
            elif action == "auto":
                self.plugin.stock_market.manual_override = None
                yield event.plain_result("✅ 股市已恢复自动模式")
            else:
                yield event.plain_result("格式: /fc admin stock <open|close|auto>")

        elif sub == "goods":
            if not self.plugin.goods_market:
                yield event.plain_result("物资市场模块未启用")
                return

            action = args[3] if len(args) >= 4 else None
            if action == "add":
                # /fc admin goods add <物资ID> <名称> <基准价> [图标] [最低价] [最高价] [波动率]
                if len(args) < 7:
                    yield event.plain_result(
                        "格式: /fc admin goods add <物资ID> <名称> <基准价> [图标] [最低价] [最高价] [波动率]"
                    )
                    return
                goods_id = args[4]
                name = args[5]
                try:
                    base_price = float(args[6])
                except ValueError:
                    yield event.plain_result("基准价格式错误")
                    return

                icon = args[7] if len(args) >= 8 else "📦"
                min_price = float(args[8]) if len(args) >= 9 else base_price * 0.1
                max_price = float(args[9]) if len(args) >= 10 else base_price * 10.0
                volatility = float(args[10]) if len(args) >= 11 else self.plugin.config.goods.goods_price_volatility

                result = self.plugin.goods_market.add_goods(
                    group_id, goods_id, name, icon, base_price, min_price, max_price, volatility
                )
                if result:
                    yield event.plain_result(f"✅ 物资 {name}({goods_id}) 添加成功，基准价 {base_price:.2f}")
                else:
                    yield event.plain_result(f"❌ 物资 {goods_id} 已存在")

            elif action == "remove":
                # /fc admin goods remove <物资ID>
                if len(args) < 5:
                    yield event.plain_result("格式: /fc admin goods remove <物资ID>")
                    return
                goods_id = args[4]
                result = self.plugin.goods_market.remove_goods(group_id, goods_id)
                if result:
                    yield event.plain_result(f"✅ 物资 {goods_id} 已移除")
                else:
                    yield event.plain_result(f"❌ 物资 {goods_id} 不存在")

            elif action == "setprice":
                # /fc admin goods setprice <物资ID> <价格>
                if len(args) < 6:
                    yield event.plain_result("格式: /fc admin goods setprice <物资ID> <价格>")
                    return
                goods_id = args[4]
                try:
                    price = float(args[5])
                except ValueError:
                    yield event.plain_result("价格格式错误")
                    return
                result = self.plugin.goods_market.set_goods_price(group_id, goods_id, price)
                if result:
                    yield event.plain_result(f"✅ 物资 {goods_id} 价格已设为 {price:.2f}")
                else:
                    yield event.plain_result(f"❌ 物资 {goods_id} 不存在")

            elif action == "setvolatility":
                # /fc admin goods setvolatility <物资ID> <波动率>
                if len(args) < 6:
                    yield event.plain_result("格式: /fc admin goods setvolatility <物资ID> <波动率>")
                    return
                goods_id = args[4]
                try:
                    vol = float(args[5])
                except ValueError:
                    yield event.plain_result("波动率格式错误")
                    return
                with self.plugin.db.session_scope() as session:
                    definition = session.query(GoodsDefinition).filter_by(
                        group_id=group_id, goods_id=goods_id
                    ).first()
                    if not definition:
                        yield event.plain_result(f"❌ 物资 {goods_id} 不存在")
                        return
                    definition.volatility = vol
                yield event.plain_result(f"✅ 物资 {goods_id} 波动率已设为 {vol}")

            elif action == "reset":
                # 重置所有物资价格至基准价
                with self.plugin.db.session_scope() as session:
                    definitions = session.query(GoodsDefinition).filter_by(
                        group_id=group_id
                    ).all()
                    if not definitions:
                        yield event.plain_result("当前群无物资定义")
                        return
                    for d in definitions:
                        market_entry = session.query(GoodsMarketPrice).filter_by(
                            group_id=group_id, goods_id=d.goods_id
                        ).first()
                        if market_entry:
                            market_entry.current_price = d.base_price
                            market_entry.previous_price = d.base_price
                yield event.plain_result("✅ 所有物资价格已重置为基准价")

            else:
                yield event.plain_result(
                    "格式: /fc admin goods <add|remove|setprice|setvolatility|reset> ..."
                )

        else:
            yield event.plain_result("未知管理指令")

    async def handle_rank(self, event, args, group_id, user_id, user_name):
        """财富排行榜（普通用户和管理员均可调用）"""
        limit = 20
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except (ValueError, IndexError):
                pass
            limit = max(5, min(50, limit))

        with self.plugin.db.session_scope() as session:
            users = session.query(UserAccount).filter_by(
                group_id=group_id
            ).order_by(UserAccount.balance.desc()).limit(limit).all()

            rank_data = []
            for u in users:
                wealth = u.balance
                if self.plugin.stock_market:
                    holdings = self.plugin.stock_market.get_holdings(group_id, u.user_id)
                    for h in holdings:
                        wealth += h['market_value']
                if self.plugin.goods_market:
                    backpack = self.plugin.goods_market.get_backpack(group_id, u.user_id)
                    for b in backpack:
                        wealth += b['total_value']
                rank_data.append({
                    'user_name': u.user_name or u.user_id,
                    'total_wealth': wealth,
                })

        rank_data.sort(key=lambda x: x['total_wealth'], reverse=True)

        result = plotter.render_rank_html(
            rank_data,
            self.plugin.config.currency.currency_name,
            self.plugin.config.currency.currency_icon,
        )

        if result:
            html_content, data = result
            url = await self._render_image(html_content, data)
            if url:
                yield event.image_result(url)
            else:
                yield event.plain_result("排行榜图片生成失败")
        else:
            yield event.plain_result("排行榜图片生成失败")

    def _get_admin_help_text(self):
        lines = [
            "⚙️ 管理员指令",
            "━━━━━━━━━━━━━━",
            "  /fc admin balance <@用户> <金额>         增减余额",
            "  /fc admin setbalance <@用户> <金额>      设置余额",
            "  /fc admin stock <open|close|auto>         股市控制",
            "  /fc admin goods add <ID> <名称> <基准价> [图标] [最低价] [最高价] [波动率]",
            "  /fc admin goods remove <物资ID>           移除物资",
            "  /fc admin goods setprice <物资ID> <价格>  设置价格",
            "  /fc admin goods setvolatility <物资ID> <波动率>",
            "  /fc admin goods reset                     重置物资价格至基准价",
        ]
        return "\n".join(lines)

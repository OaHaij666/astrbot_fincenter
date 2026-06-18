"""管理员处理器

处理余额管理、股市控制、物资管理等管理员指令。
排行榜已移至普通用户指令，此处仅保留管理员入口。
图片渲染对齐参考项目: html_render → 文件路径 → event.image_result(文件路径)
"""
from ..core.database import UserAccount, GoodsDefinition, GoodsMarketPrice
from ..services.command_registry import list_other_plugin_commands
from ..utils import plotter


class AdminHandler:
    def __init__(self, plugin, html_render):
        self.plugin = plugin

    async def handle(self, event, args, raw_group_id, group_id, user_id, user_name):
        if str(user_id) not in self.plugin.config.admin_id_set:
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
                            {'cmd': '/fc admin stock enable [分组ID]', 'desc': '本群启用股市/绑定分组'},
                            {'cmd': '/fc admin stock disable', 'desc': '本群禁用股市'},
                            {'cmd': '/fc admin stock group [分组ID]', 'desc': '查看/切换股市分组'},
                            {'cmd': '/fc admin stock open', 'desc': '强制开市'},
                            {'cmd': '/fc admin stock close', 'desc': '强制休市'},
                            {'cmd': '/fc admin stock auto', 'desc': '恢复自动模式'},
                        ],
                    },
                    {
                        'section_name': '📦 物资管理',
                        'commands': [
                            {'cmd': '/fc admin goods enable [分组ID]', 'desc': '本群启用物资/绑定分组'},
                            {'cmd': '/fc admin goods disable', 'desc': '本群禁用物资'},
                            {'cmd': '/fc admin goods group [分组ID]', 'desc': '查看/切换物资分组'},
                            {'cmd': '/fc admin goods add <ID> <名称> <价>', 'desc': '添加物资'},
                            {'cmd': '/fc admin goods remove <物资ID>', 'desc': '移除物资'},
                            {'cmd': '/fc admin goods setprice <ID> <价>', 'desc': '设置价格'},
                            {'cmd': '/fc admin goods setvolatility <ID> <率>', 'desc': '设置波动率'},
                            {'cmd': '/fc admin goods reset', 'desc': '重置所有物资价格至基准价'},
                        ],
                    },
                    {
                        'section_name': '💴 付费指令',
                        'commands': [
                            {'cmd': '/fc admin paidcmd list', 'desc': '查看当前付费组配置'},
                            {'cmd': '/fc admin paidcmd group [组ID]', 'desc': '查看/切换本群付费组'},
                            {'cmd': '/fc admin paidcmd on|off [组ID]', 'desc': '启停本群付费拦截'},
                            {'cmd': '/fc admin paidcmd scan', 'desc': '扫描其他插件命令'},
                            {'cmd': '/fc admin paidcmd add <cmd> <cost> [描述]', 'desc': '配置付费指令'},
                            {'cmd': '/fc admin paidcmd remove <cmd>', 'desc': '移除付费指令'},
                            {'cmd': '/fc admin paidcmd disable <cmd>', 'desc': '禁用付费指令'},
                        ],
                    },
                ],
                tips=['上述指令仅限管理员使用，@用户 可直接用 QQ号'],
            )
            if result:
                html_content, data = result
                image_path = await self.plugin._render_image(html_content, data)
                if image_path:
                    yield event.image_result(image_path)
                    return
            yield event.plain_result(self._get_admin_help_text())
            return

        sub = args[2]
        currency_name = self.plugin.config.currency.currency_name
        stock_enabled, stock_group_id = self.plugin.get_stock_binding(raw_group_id)
        goods_enabled, goods_group_id = self.plugin.get_goods_binding(raw_group_id)

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
            action = args[3] if len(args) >= 4 else None
            if action in ("enable", "on"):
                target_group = args[4] if len(args) >= 5 else raw_group_id
                self.plugin.set_market_binding(raw_group_id, "stock", target_group, True)
                if not self.plugin.stock_market and self.plugin.config.stock.stock_enabled:
                    self.plugin.enable_stock_market(update_config=False)
                yield event.plain_result(f"✅ 本群股市已启用，绑定分组: {target_group}")
            elif action in ("disable", "off"):
                self.plugin.set_market_binding(raw_group_id, "stock", stock_group_id, False)
                yield event.plain_result(f"✅ 本群股市已禁用（原分组: {stock_group_id}）")
            elif action == "group":
                if len(args) >= 5:
                    target_group = args[4]
                    self.plugin.set_market_binding(raw_group_id, "stock", target_group, True)
                    yield event.plain_result(f"✅ 本群股市已切换到分组: {target_group}")
                else:
                    status = "启用" if stock_enabled else "禁用"
                    yield event.plain_result(f"本群股市状态: {status}\n当前股市分组: {stock_group_id}")
            elif action in ("open", "close", "auto"):
                if not self.plugin.stock_market:
                    yield event.plain_result("股市模块未启用")
                    return
                self.plugin.stock_market.ensure_group_initialized(stock_group_id)
                if action == "open":
                    self.plugin.stock_market.set_open(True)
                    yield event.plain_result(f"✅ 股市分组 {stock_group_id} 已强制开市")
                elif action == "close":
                    self.plugin.stock_market.set_open(False)
                    yield event.plain_result(f"✅ 股市分组 {stock_group_id} 已强制休市")
                else:
                    self.plugin.stock_market.manual_override = None
                    yield event.plain_result(f"✅ 股市分组 {stock_group_id} 已恢复自动模式")
            else:
                yield event.plain_result("格式: /fc admin stock <enable [分组ID]|disable|group [分组ID]|open|close|auto>")

        elif sub == "goods":
            action = args[3] if len(args) >= 4 else None
            if action in ("enable", "on"):
                target_group = args[4] if len(args) >= 5 else raw_group_id
                self.plugin.set_market_binding(raw_group_id, "goods", target_group, True)
                if not self.plugin.goods_market and self.plugin.config.goods.goods_enabled:
                    self.plugin.enable_goods_market(update_config=False)
                yield event.plain_result(f"✅ 本群物资模块已启用，绑定分组: {target_group}")
                return
            if action in ("disable", "off"):
                self.plugin.set_market_binding(raw_group_id, "goods", goods_group_id, False)
                yield event.plain_result(f"✅ 本群物资模块已禁用（原分组: {goods_group_id}）")
                return
            if action == "group":
                if len(args) >= 5:
                    target_group = args[4]
                    self.plugin.set_market_binding(raw_group_id, "goods", target_group, True)
                    yield event.plain_result(f"✅ 本群物资模块已切换到分组: {target_group}")
                else:
                    status = "启用" if goods_enabled else "禁用"
                    yield event.plain_result(f"本群物资状态: {status}\n当前物资分组: {goods_group_id}")
                return

            if not self.plugin.goods_market:
                yield event.plain_result("物资市场模块未启用")
                return
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
                    goods_group_id, goods_id, name, icon, base_price, min_price, max_price, volatility
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
                result = self.plugin.goods_market.remove_goods(goods_group_id, goods_id)
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
                result = self.plugin.goods_market.set_goods_price(goods_group_id, goods_id, price)
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
                        group_id=goods_group_id, goods_id=goods_id
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
                        group_id=goods_group_id
                    ).all()
                    if not definitions:
                        yield event.plain_result("当前群无物资定义")
                        return
                    for d in definitions:
                        market_entry = session.query(GoodsMarketPrice).filter_by(
                            group_id=goods_group_id, goods_id=d.goods_id
                        ).first()
                        if market_entry:
                            market_entry.current_price = d.base_price
                            market_entry.previous_price = d.base_price
                yield event.plain_result("✅ 所有物资价格已重置为基准价")

            else:
                yield event.plain_result(
                    "格式: /fc admin goods <add|remove|setprice|setvolatility|reset> ..."
                )

        elif sub in ("paidcmd", "付费", "付费指令"):
            async for r in self._handle_paidcmd(event, args, raw_group_id, group_id):
                yield r

        else:
            yield event.plain_result("未知管理指令")

    async def _handle_paidcmd(self, event, args, raw_group_id, group_id):
        action = args[3] if len(args) >= 4 else None
        service = self.plugin.paid_command_service
        paid_enabled, paid_group_id = self.plugin.get_paid_binding(raw_group_id)

        # 中文别名映射
        action_map = {
            "列表": "list",
            "查看": "list",
            "扫描": "scan",
            "添加": "add",
            "新增": "add",
            "分组": "group",
            "删除": "remove",
            "移除": "remove",
            "切换": "toggle",
            "启用": "enable",
            "禁用": "disable",
            "开启": "on",
            "关闭": "off",
        }
        action = action_map.get(action, action)

        if action in ("group", "on", "off"):
            if action == "group" and len(args) >= 5:
                target_group = args[4]
                self.plugin.set_market_binding(raw_group_id, "paid", target_group, True)
                yield event.plain_result(f"✅ 本群付费配置已切换到组: {target_group}")
                return
            if action == "on":
                target_group = args[4] if len(args) >= 5 else raw_group_id
                self.plugin.set_market_binding(raw_group_id, "paid", target_group, True)
                yield event.plain_result(f"✅ 本群付费拦截已启用，绑定组: {target_group}")
                return
            if action == "off":
                self.plugin.set_market_binding(raw_group_id, "paid", paid_group_id, False)
                yield event.plain_result(f"✅ 本群付费拦截已禁用（原组: {paid_group_id}）")
                return
            status = "启用" if paid_enabled else "禁用"
            yield event.plain_result(
                f"本群付费拦截: {status}\n"
                f"当前付费组: {paid_group_id}\n\n"
                "切换: /fc admin paidcmd group <组ID>\n"
                "启用: /fc admin paidcmd on [组ID]\n"
                "禁用: /fc admin paidcmd off"
            )
            return

        if action in (None, "list"):
            rows = service.list_paid_commands(paid_group_id)
            if not rows:
                yield event.plain_result(
                    "本群暂无付费指令配置\n\n"
                    f"当前付费组: {paid_group_id}\n"
                    "添加: /fc admin paidcmd add <cmd> <cost> [描述]\n"
                    "扫描: /fc admin paidcmd scan\n"
                    "示例: /fc admin paidcmd add weather 5 查天气收费"
                )
                return
            currency_icon = self.plugin.config.currency.currency_icon
            status = "启用" if paid_enabled else "禁用"
            lines = [f"💴 付费指令配置（组: {paid_group_id} / {status}）", "━━━━━━━━━━━━━━"]
            for r in rows:
                state = "✅" if r["enabled"] else "🚫"
                scope = "全局" if r["group_id"] == service.GLOBAL_GROUP else r["group_id"]
                desc = f"  {r['description']}" if r["description"] else ""
                lines.append(
                    f"{state} [{scope}] {r['command']}  "
                    f"{currency_icon}{r['cost']:.2f}{desc}"
                )
            yield event.plain_result("\n".join(lines))
            return

        if action == "scan":
            cmds = list_other_plugin_commands()
            if not cmds:
                yield event.plain_result("未发现可拦截的其他插件命令")
                return
            lines = ["🔍 可被拦截的其他插件命令", "━━━━━━━━━━━━━━"]
            for c in cmds[:80]:
                desc = f"  - {c['desc']}" if c["desc"] else ""
                lines.append(f"[{c['plugin']}] {c['command']}{desc}")
            if len(cmds) > 80:
                lines.append(f"…… 共 {len(cmds)} 条，仅显示前 80")
            yield event.plain_result("\n".join(lines))
            return

        if action == "add":
            if len(args) < 6:
                yield event.plain_result(
                    "格式: /fc admin paidcmd add <cmd> <cost> [描述]\n"
                    "示例: /fc admin paidcmd add weather 5 查天气"
                )
                return
            command = args[4]
            try:
                cost = float(args[5])
            except ValueError:
                yield event.plain_result("费用格式错误")
                return
            description = " ".join(args[6:]) if len(args) > 6 else ""
            scope = paid_group_id
            if command.startswith("*:"):
                scope = service.GLOBAL_GROUP
                command = command[2:]
            ok = service.add_paid_command(scope, command, cost, description)
            if ok:
                scope_label = "全局" if scope == service.GLOBAL_GROUP else f"付费组 {scope}"
                yield event.plain_result(
                    f"✅ 已为 {scope_label} 配置付费指令 {command}: {cost:.2f}"
                )
            else:
                yield event.plain_result("❌ 添加失败")
            return

        if action == "remove":
            if len(args) < 5:
                yield event.plain_result(
                    "格式: /fc admin paidcmd remove <cmd> [*]\n"
                    "示例: /fc admin paidcmd remove weather"
                )
                return
            command = args[4]
            scope = paid_group_id
            if len(args) >= 6 and args[5] == "*":
                scope = service.GLOBAL_GROUP
            ok = service.remove_paid_command(scope, command)
            if ok:
                yield event.plain_result(f"✅ 已移除付费指令 {command}")
            else:
                yield event.plain_result(f"❌ 未找到 {command}")
            return

        if action in ("toggle", "enable", "disable"):
            if len(args) < 5:
                yield event.plain_result(
                    "格式: /fc admin paidcmd <toggle|enable|disable> <cmd> [*]\n"
                    "示例: /fc admin paidcmd disable weather"
                )
                return
            command = args[4]
            scope = paid_group_id
            if len(args) >= 6 and args[5] == "*":
                scope = service.GLOBAL_GROUP
            enabled = action != "disable"
            ok = service.toggle_paid_command(scope, command, enabled)
            if ok:
                state = "启用" if enabled else "禁用"
                yield event.plain_result(f"✅ 已{state}付费指令 {command}")
            else:
                yield event.plain_result(f"❌ 未找到 {command}")
            return

        yield event.plain_result(
            "付费指令管理:\n\n"
            "/fc admin paidcmd list\n"
            "/fc admin paidcmd group [组ID]\n"
            "/fc admin paidcmd on|off [组ID]\n"
            "/fc admin paidcmd scan\n"
            "/fc admin paidcmd add <cmd> <cost> [描述]\n"
            "/fc admin paidcmd remove <cmd>\n"
            "/fc admin paidcmd disable <cmd>\n"
            "/fc admin paidcmd enable <cmd>"
        )

    async def handle_rank(self, event, args, raw_group_id, group_id, user_id, user_name):
        """财富排行榜（普通用户和管理员均可调用）"""
        limit = 20
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except (ValueError, IndexError):
                pass
            limit = max(5, min(50, limit))

        stock_enabled, stock_group_id = self.plugin.get_stock_binding(raw_group_id)
        goods_enabled, goods_group_id = self.plugin.get_goods_binding(raw_group_id)

        with self.plugin.db.session_scope() as session:
            users = session.query(UserAccount).filter_by(
                group_id=group_id
            ).order_by(UserAccount.balance.desc()).limit(limit).all()

            rank_data = []
            for u in users:
                wealth = float(u.balance or 0)
                if stock_enabled and self.plugin.stock_market:
                    holdings = self.plugin.stock_market.get_holdings(stock_group_id, u.user_id)
                    for h in holdings:
                        wealth += float(h.get('market_value', 0))
                if goods_enabled and self.plugin.goods_market:
                    backpack = self.plugin.goods_market.get_backpack(goods_group_id, u.user_id)
                    for b in backpack:
                        wealth += float(b.get('total_value', 0))
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
            image_path = await self.plugin._render_image(html_content, data)
            if image_path:
                yield event.image_result(image_path)
                return

        # 文字回退
        currency_icon = self.plugin.config.currency.currency_icon
        lines = [f"🏆 财富排行榜 TOP{len(rank_data)}", "━━━━━━━━━━━━━━"]
        for i, r in enumerate(rank_data[:20], 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            lines.append(f"{medal} {r['user_name']}: {currency_icon}{r['total_wealth']:.2f}")
        yield event.plain_result("\n".join(lines))

    def _get_admin_help_text(self):
        lines = [
            "⚙️ 管理员指令",
            "━━━━━━━━━━━━━━",
            "  /fc admin balance <@用户> <金额>         增减余额",
            "  /fc admin setbalance <@用户> <金额>      设置余额",
            "  /fc admin stock enable [分组ID]          本群启用股市并绑定分组",
            "  /fc admin stock disable                 本群禁用股市",
            "  /fc admin stock group [分组ID]           查看/切换本群股市分组",
            "  /fc admin stock <open|close|auto>        当前股市分组开休市控制",
            "  /fc admin goods enable [分组ID]          本群启用物资并绑定分组",
            "  /fc admin goods disable                 本群禁用物资",
            "  /fc admin goods group [分组ID]           查看/切换本群物资分组",
            "  /fc admin goods add <ID> <名称> <基准价> [图标] [最低价] [最高价] [波动率]",
            "  /fc admin goods remove <物资ID>           移除物资",
            "  /fc admin goods setprice <物资ID> <价格>  设置价格",
            "  /fc admin goods setvolatility <物资ID> <波动率>",
            "  /fc admin goods reset                     重置物资价格至基准价",
            "",
            "💴 付费指令:",
            "  /fc admin paidcmd list                    查看当前付费组配置",
            "  /fc admin paidcmd group [组ID]             查看/切换本群付费组",
            "  /fc admin paidcmd on|off [组ID]            启停本群付费拦截",
            "  /fc admin paidcmd scan                    扫描其他插件命令",
            "  /fc admin paidcmd add <cmd> <cost> [描述]  配置付费指令",
            "  /fc admin paidcmd remove <cmd>             移除付费指令",
            "  /fc admin paidcmd disable <cmd>            禁用付费指令",
            "  /fc admin paidcmd enable <cmd>             启用付费指令",
        ]
        return "\n".join(lines)

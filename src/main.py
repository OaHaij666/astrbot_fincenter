"""FinCenter 插件主模块

提供 AstrBot 插件入口，负责配置解析、数据库初始化、
市场引擎生命周期管理和指令路由。
"""
import os

from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

from .config import FinCenterConfig
from .core.database import DB, ChatRewardState, UserAccount, PaidCommand, get_china_time
from .markets.stock import StockMarket
from .markets.goods import GoodsMarket
from .handlers import AccountHandler, StockHandler, GoodsHandler, AdminHandler
from .utils import plotter
from migrations.migrate import migrate, set_paths as set_migrate_paths


@register("FinCenter", "FinCenter Team", "群聊财富中心 - 开户签到股市交易物资贸易", "1.0.0")
class FinCenterPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self._raw_config = config or {}

        self._setup_paths()
        self._setup_config()
        self._setup_database()
        self._setup_handlers()
        self._setup_markets()

    # ── 辅助方法 ──────────────────────────────────────────────

    def _extract_group_id(self, event: AstrMessageEvent) -> str:
        """从 unified_msg_origin 提取群号，私聊场景回退到 user_id"""
        origin = getattr(event, "unified_msg_origin", "") or ""
        parts = origin.split(":")
        if len(parts) >= 3 and "Group" in parts[1]:
            group_id = parts[2]
        else:
            group_id = str(event.get_sender_id())
        return self._resolve_group_id(group_id)

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        """从 event 获取发送者昵称"""
        sender = getattr(getattr(event, "message_obj", None), "sender", None)
        if sender:
            name = getattr(sender, "nickname", None) or getattr(sender, "name", None)
            if name:
                return name
        return str(event.get_sender_id())

    # ── 初始化 ────────────────────────────────────────────────

    def _setup_paths(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(self.base_dir, 'data')
        self.assets_dir = os.path.join(self.base_dir, 'assets')
        self.cache_dir = os.path.join(self.data_dir, 'cache')

        for d in [self.data_dir, self.assets_dir, self.cache_dir]:
            os.makedirs(d, exist_ok=True)

        plotter.set_paths(base_dir=self.base_dir)
        set_migrate_paths(base_dir=self.base_dir)

    def _setup_config(self):
        self.config = FinCenterConfig.from_dict(self._raw_config)

    def _setup_database(self):
        db_file = os.path.join(self.data_dir, "fincenter.db")
        self.db = DB(db_file)
        migrate()

    def _setup_handlers(self):
        self.account_handler = AccountHandler(self)
        self.stock_handler = StockHandler(self)
        self.goods_handler = GoodsHandler(self)
        self.admin_handler = AdminHandler(self)

    def _setup_markets(self):
        self.stock_market = None
        self.goods_market = None

        if self.config.stock.stock_enabled:
            self.stock_market = StockMarket(
                self.db,
                stock_config=self.config.stock,
                news_config=self.config.stock_news,
            )
            self.stock_market.start()
            logger.info("Stock market started")

        if self.config.goods.goods_enabled:
            self.goods_market = GoodsMarket(
                self.db,
                config=self.config.goods,
            )
            self.goods_market.start()
            logger.info("Goods market started")

    def _resolve_group_id(self, group_id: str) -> str:
        if self.config.basic.cross_group_data:
            return "__global__"
        return group_id

    def _check_group_allowed(self, group_id: str) -> bool:
        cfg = self.config.basic
        if not cfg.group_filter_enabled:
            return True
        if cfg.group_whitelist and group_id not in cfg.group_whitelist:
            return False
        if cfg.group_blacklist and group_id in cfg.group_blacklist:
            return False
        return True

    def _process_chat_reward(self, group_id: str, user_id: str, user_name: str):
        cfg = self.config.chat_reward
        if not cfg.chat_reward_enabled:
            return

        with self.db.session_scope() as session:
            user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not user:
                return

            now = get_china_time()
            today = now.strftime('%Y-%m-%d')

            state = session.query(ChatRewardState).filter_by(
                group_id=group_id, user_id=user_id
            ).first()

            if not state:
                state = ChatRewardState(
                    group_id=group_id,
                    user_id=user_id,
                    last_reward_time=now,
                    daily_count=1,
                    last_reset_date=today,
                )
                session.add(state)
                session.flush()
            else:
                if state.last_reset_date != today:
                    state.daily_count = 0
                    state.last_reset_date = today

                if state.daily_count >= cfg.chat_reward_daily_limit:
                    return

                if state.last_reward_time:
                    elapsed = (now - state.last_reward_time).total_seconds()
                    if elapsed < cfg.chat_reward_cooldown:
                        return

            user.balance += cfg.chat_reward_amount
            user.total_earned += cfg.chat_reward_amount
            state.last_reward_time = now
            state.daily_count += 1

    def _check_paid_command(self, message: str, group_id: str, user_id: str) -> str | None:
        cfg = self.config.paid_cmd
        if not cfg.paid_cmd_enabled:
            return None

        matched_prefix = None
        for prefix in cfg.paid_cmd_prefixes:
            if message.startswith(prefix) and len(message) > len(prefix):
                matched_prefix = prefix
                break

        if not matched_prefix:
            return None

        cmd_text = message[len(matched_prefix):].split()[0] if message[len(matched_prefix):] else ""
        if not cmd_text:
            return None

        with self.db.session_scope() as session:
            paid_cmd = session.query(PaidCommand).filter_by(
                group_id=group_id, command=cmd_text, enabled=1
            ).first()

            if not paid_cmd:
                return None

            is_admin = str(user_id) in self.config.basic.admin_ids
            if is_admin and cfg.paid_cmd_ignore_admin:
                return None

            user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not user:
                return cfg.paid_cmd_insufficient_msg.format(
                    cost=paid_cmd.cost,
                    currency=self.config.currency.currency_name,
                    balance=0.0,
                )

            if user.balance < paid_cmd.cost:
                return cfg.paid_cmd_insufficient_msg.format(
                    cost=paid_cmd.cost,
                    currency=self.config.currency.currency_name,
                    balance=user.balance,
                )

            user.balance -= paid_cmd.cost
            user.total_spent += paid_cmd.cost

            if cfg.paid_cmd_deduct_msg:
                return cfg.paid_cmd_deduct_msg.format(
                    cost=paid_cmd.cost,
                    currency=self.config.currency.currency_name,
                    balance=user.balance,
                )

        return None

    # ── 命令注册 ──────────────────────────────────────────────

    # 第一级：/fc 命令组
    @filter.command_group("fc")
    def fc_group(self):
        """财富中心"""
        pass

    # ── 一、账户指令 ──────────────────────────────────────────

    @fc_group.command("open")
    async def fc_open(self, event: AstrMessageEvent, args: str = ""):
        """开户。为自己或他人创建金融中心账户。

        用法:
        - /fc open
        - /fc open @用户
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "open"] + (args.split() if args else [])
        async for result in self.account_handler.handle_open(event, arg_list, group_id, user_id, user_name):
            yield result

    @fc_group.command("me")
    async def fc_me(self, event: AstrMessageEvent):
        """查看我的账户信息。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.account_handler.handle_me(event, group_id, user_id, user_name):
            yield result

    @fc_group.command("sign")
    async def fc_sign(self, event: AstrMessageEvent):
        """每日签到。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.account_handler.handle_sign(event, group_id, user_id, user_name):
            yield result

    @fc_group.command("transfer")
    async def fc_transfer(self, event: AstrMessageEvent, args: str = ""):
        """转账。

        用法:
        - /fc transfer @用户 金额
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "transfer"] + (args.split() if args else [])
        async for result in self.account_handler.handle_transfer(event, arg_list, group_id, user_id, user_name):
            yield result

    @fc_group.command("rank")
    async def fc_rank(self, event: AstrMessageEvent, args: str = ""):
        """财富排行榜。

        用法:
        - /fc rank [条数]
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "rank"] + (args.split() if args else [])
        async for result in self.admin_handler.handle_rank(event, arg_list, group_id, user_id, user_name):
            yield result

    # ── 二、股市指令 /fc stock ────────────────────────────────

    @fc_group.group("stock")
    def stock_group(self):
        """股市"""
        pass

    @stock_group.command("market")
    async def stock_market(self, event: AstrMessageEvent):
        """股市总览（图片）。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.stock_handler.handle(event, ["fc", "stock", "market"], group_id, user_id, user_name):
            yield result

    @stock_group.command("buy")
    async def stock_buy(self, event: AstrMessageEvent, args: str = ""):
        """买入股票。

        用法:
        - /fc stock buy <代码> <数量>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "stock", "buy"] + (args.split() if args else [])
        async for result in self.stock_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @stock_group.command("sell")
    async def stock_sell(self, event: AstrMessageEvent, args: str = ""):
        """卖出股票。

        用法:
        - /fc stock sell <代码> <数量>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "stock", "sell"] + (args.split() if args else [])
        async for result in self.stock_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @stock_group.command("assets")
    async def stock_assets(self, event: AstrMessageEvent):
        """查看我的股票持仓。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.stock_handler.handle(event, ["fc", "stock", "assets"], group_id, user_id, user_name):
            yield result

    @stock_group.command("kline")
    async def stock_kline(self, event: AstrMessageEvent, args: str = ""):
        """查看K线图（图片）。

        用法:
        - /fc stock kline <代码> [条数]
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "stock", "kline"] + (args.split() if args else [])
        async for result in self.stock_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @stock_group.command("news")
    async def stock_news(self, event: AstrMessageEvent):
        """查看今日市场新闻。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.stock_handler.handle(event, ["fc", "stock", "news"], group_id, user_id, user_name):
            yield result

    @stock_group.command("event")
    async def stock_event(self, event: AstrMessageEvent, args: str = ""):
        """手动触发市场新闻事件（管理员专用）。

        用法:
        - /fc stock event [代码]
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "stock", "event"] + (args.split() if args else [])
        async for result in self.stock_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    # ── 三、物资指令 /fc goods ────────────────────────────────

    @fc_group.group("goods")
    def goods_group(self):
        """物资市场"""
        pass

    @goods_group.command("market")
    async def goods_market(self, event: AstrMessageEvent):
        """物资市场总览（图片）。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.goods_handler.handle(event, ["fc", "goods", "market"], group_id, user_id, user_name):
            yield result

    @goods_group.command("buy")
    async def goods_buy(self, event: AstrMessageEvent, args: str = ""):
        """买入物资。

        用法:
        - /fc goods buy <物资ID> <数量>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "goods", "buy"] + (args.split() if args else [])
        async for result in self.goods_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @goods_group.command("sell")
    async def goods_sell(self, event: AstrMessageEvent, args: str = ""):
        """卖出物资。

        用法:
        - /fc goods sell <物资ID> <数量>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "goods", "sell"] + (args.split() if args else [])
        async for result in self.goods_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @goods_group.command("backpack")
    async def goods_backpack(self, event: AstrMessageEvent):
        """查看我的物资背包。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.goods_handler.handle(event, ["fc", "goods", "backpack"], group_id, user_id, user_name):
            yield result

    # ── 四、管理员指令 /fc admin ──────────────────────────────

    @fc_group.group("admin")
    def admin_group(self):
        """管理员"""
        pass

    @admin_group.command("balance")
    async def admin_balance(self, event: AstrMessageEvent, args: str = ""):
        """为用户增减余额。

        用法:
        - /fc admin balance <@用户> <金额>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "admin", "balance"] + (args.split() if args else [])
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_group.command("setbalance")
    async def admin_setbalance(self, event: AstrMessageEvent, args: str = ""):
        """直接设置用户余额。

        用法:
        - /fc admin setbalance <@用户> <金额>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "admin", "setbalance"] + (args.split() if args else [])
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_group.group("stock")
    def admin_stock_group(self):
        """股市控制"""
        pass

    @admin_stock_group.command("open")
    async def admin_stock_open(self, event: AstrMessageEvent):
        """强制开市。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "stock", "open"], group_id, user_id, user_name):
            yield result

    @admin_stock_group.command("close")
    async def admin_stock_close(self, event: AstrMessageEvent):
        """强制休市。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "stock", "close"], group_id, user_id, user_name):
            yield result

    @admin_stock_group.command("auto")
    async def admin_stock_auto(self, event: AstrMessageEvent):
        """恢复股市自动交易模式。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "stock", "auto"], group_id, user_id, user_name):
            yield result

    @admin_group.group("goods")
    def admin_goods_group(self):
        """物资管理"""
        pass

    @admin_goods_group.command("add")
    async def admin_goods_add(self, event: AstrMessageEvent, args: str = ""):
        """添加新物资。

        用法:
        - /fc admin goods add <物资ID> <名称> <基准价> [图标] [最低价] [最高价] [波动率]
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "admin", "goods", "add"] + (args.split() if args else [])
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_goods_group.command("remove")
    async def admin_goods_remove(self, event: AstrMessageEvent, args: str = ""):
        """移除物资。

        用法:
        - /fc admin goods remove <物资ID>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "admin", "goods", "remove"] + (args.split() if args else [])
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_goods_group.command("setprice")
    async def admin_goods_setprice(self, event: AstrMessageEvent, args: str = ""):
        """手动设置物资当前价格。

        用法:
        - /fc admin goods setprice <物资ID> <价格>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "admin", "goods", "setprice"] + (args.split() if args else [])
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_goods_group.command("setvolatility")
    async def admin_goods_setvolatility(self, event: AstrMessageEvent, args: str = ""):
        """设置物资价格波动率。

        用法:
        - /fc admin goods setvolatility <物资ID> <波动率>
        """
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = ["fc", "admin", "goods", "setvolatility"] + (args.split() if args else [])
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_goods_group.command("reset")
    async def admin_goods_reset(self, event: AstrMessageEvent):
        """重置所有物资价格至基准价。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "goods", "reset"], group_id, user_id, user_name):
            yield result

    # ── 生命周期 ──────────────────────────────────────────────

    async def terminate(self):
        """优雅关闭所有市场引擎"""
        if self.stock_market:
            self.stock_market.stop()
            logger.info("Stock market stopped")
        if self.goods_market:
            self.goods_market.stop()
            logger.info("Goods market stopped")
        await plotter.shutdown()

    def __del__(self):
        if self.stock_market:
            self.stock_market.stop()
        if self.goods_market:
            self.goods_market.stop()

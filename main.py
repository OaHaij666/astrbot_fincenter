"""FinCenter 插件入口

AstrBot 要求插件类定义在根 main.py，handler 的 __module__ 才会与框架的
module_path 匹配，从而正确绑定 self。
"""
import os
import sys
from pathlib import Path

# AstrBot extracts plugins to data/plugins/<name>/ — ensure the plugin root is on sys.path
_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from src.config import FinCenterConfig
from src.core.database import DB, ChatRewardState, UserAccount, PaidCommand, get_china_time
from src.markets.stock import StockMarket
from src.markets.goods import GoodsMarket
from src.handlers import AccountHandler, StockHandler, GoodsHandler, AdminHandler
from src.utils import plotter
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
        return event.get_sender_name() or str(event.get_sender_id())

    @staticmethod
    def _parse_args(event: AstrMessageEvent) -> list:
        """从 event.message_str 解析出参数列表"""
        return event.message_str.split()

    # ── 初始化 ────────────────────────────────────────────────

    def _setup_paths(self):
        # 插件类现在在根 main.py，实际代码在 src/ 下
        plugin_root = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = os.path.join(plugin_root, 'src')
        self.data_dir = str(Path(get_astrbot_data_path()) / "plugin_data" / self.name)
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
    # 注意：根据 AstrBot 官方文档
    #   - 命令组函数不能有 self 参数：def fc_group(): pass
    #   - handler 前两个参数必须为 self 和 event
    #   - 带参指令由框架自动解析，但我们用 event.message_str 自行解析更灵活

    # 第一级：/fc 命令组
    @filter.command_group("fc")
    def fc_group():
        """财富中心"""
        pass

    # ── 一、账户指令 ──────────────────────────────────────────

    @fc_group.command("open")
    async def fc_open(self, event: AstrMessageEvent):
        """开户。为自己或他人创建金融中心账户。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
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
    async def fc_transfer(self, event: AstrMessageEvent):
        """转账。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.account_handler.handle_transfer(event, arg_list, group_id, user_id, user_name):
            yield result

    @fc_group.command("rank")
    async def fc_rank(self, event: AstrMessageEvent):
        """财富排行榜。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle_rank(event, arg_list, group_id, user_id, user_name):
            yield result

    # ── 二、股市指令 /fc stock ────────────────────────────────

    @fc_group.group("stock")
    def stock_group():
        """股市"""
        pass

    @stock_group.command("market")
    async def stock_market(self, event: AstrMessageEvent):
        """股市总览。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.stock_handler.handle(event, ["fc", "stock", "market"], group_id, user_id, user_name):
            yield result

    @stock_group.command("buy")
    async def stock_buy(self, event: AstrMessageEvent):
        """买入股票。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.stock_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @stock_group.command("sell")
    async def stock_sell(self, event: AstrMessageEvent):
        """卖出股票。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
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
    async def stock_kline(self, event: AstrMessageEvent):
        """查看K线图。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @stock_group.command("event")
    async def stock_event(self, event: AstrMessageEvent):
        """手动触发市场新闻事件（管理员专用）。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.stock_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    # ── 三、物资指令 /fc goods ────────────────────────────────

    @fc_group.group("goods")
    def goods_group():
        """物资市场"""
        pass

    @goods_group.command("market")
    async def goods_market(self, event: AstrMessageEvent):
        """物资市场总览。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.goods_handler.handle(event, ["fc", "goods", "market"], group_id, user_id, user_name):
            yield result

    @goods_group.command("buy")
    async def goods_buy(self, event: AstrMessageEvent):
        """买入物资。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.goods_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @goods_group.command("sell")
    async def goods_sell(self, event: AstrMessageEvent):
        """卖出物资。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
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
    def admin_group():
        """管理员"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_group.command("balance")
    async def admin_balance(self, event: AstrMessageEvent):
        """为用户增减余额。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_group.command("setbalance")
    async def admin_setbalance(self, event: AstrMessageEvent):
        """直接设置用户余额。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @admin_group.group("stock")
    def admin_stock_group():
        """股市控制"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_stock_group.command("open")
    async def admin_stock_open(self, event: AstrMessageEvent):
        """强制开市。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "stock", "open"], group_id, user_id, user_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_stock_group.command("close")
    async def admin_stock_close(self, event: AstrMessageEvent):
        """强制休市。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "stock", "close"], group_id, user_id, user_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_stock_group.command("auto")
    async def admin_stock_auto(self, event: AstrMessageEvent):
        """恢复股市自动交易模式。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        async for result in self.admin_handler.handle(event, ["fc", "admin", "stock", "auto"], group_id, user_id, user_name):
            yield result

    @admin_group.group("goods")
    def admin_goods_group():
        """物资管理"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_goods_group.command("add")
    async def admin_goods_add(self, event: AstrMessageEvent):
        """添加新物资。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_goods_group.command("remove")
    async def admin_goods_remove(self, event: AstrMessageEvent):
        """移除物资。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_goods_group.command("setprice")
    async def admin_goods_setprice(self, event: AstrMessageEvent):
        """手动设置物资当前价格。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @admin_goods_group.command("setvolatility")
    async def admin_goods_setvolatility(self, event: AstrMessageEvent):
        """设置物资价格波动率。"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        arg_list = self._parse_args(event)
        async for result in self.admin_handler.handle(event, arg_list, group_id, user_id, user_name):
            yield result

    # ── 清理 ──────────────────────────────────────────────────

    async def terminate(self):
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

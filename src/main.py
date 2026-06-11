"""FinCenter 插件主模块

提供 AstrBot 插件入口，负责配置解析、数据库初始化、
市场引擎生命周期管理和指令路由。
"""
import asyncio
import os
import tempfile
import logging
from typing import Any

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

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

    # ---- 从消息中提取路由参数 ----
    def _route_info(self, event: AstrMessageEvent):
        group_id = event.get_group_id() or "default"
        user_id = event.get_sender_id()
        user_name = event.get_sender_name() or user_id
        if not self._check_group_allowed(group_id):
            return None
        group_id = self._resolve_group_id(group_id)
        return group_id, user_id, user_name

    def _args(self, event: AstrMessageEvent, sub: str) -> list:
        """重建 handlers 期望的完整 args 格式 ["/fc", sub, ...]"""
        parts = event.message_str.split()
        if parts[0] == "/fc":
            return parts  # 完整消息，直接返回
        # command_group 可能剥除了前缀，手动补回
        return ["/fc", sub] + parts

    # ---- /fc 指令组 ----
    @filter.command_group("fc")
    def fc_group(self):
        pass

    @fc_group.command("help")
    async def fc_help(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        img_buf = await plotter.render_help_image(
            title=f"💰 {self.config.currency.currency_name} 金融中心",
            sections=[{'commands': [
                {'cmd': 'fc open', 'desc': '开户'},
                {'cmd': 'fc me', 'desc': '我的账户'},
                {'cmd': 'fc sign', 'desc': '每日签到'},
                {'cmd': 'fc transfer <@> <金额>', 'desc': '转账'},
                {'cmd': 'fc rank [条数]', 'desc': '财富排行榜'},
                {'cmd': 'fc stock', 'desc': '股市帮助'},
                {'cmd': 'fc goods', 'desc': '物资帮助'},
                {'cmd': 'fc admin', 'desc': '管理员指令（限管理员）', 'admin': True},
            ]}],
            tips=['输入 fc <子命令> 查看详细帮助，如 fc stock'],
        )
        if img_buf:
            fd, path = tempfile.mkstemp(suffix=".png")
            with os.fdopen(fd, 'wb') as f:
                f.write(img_buf.getvalue())
            yield event.image_result(path)
        else:
            yield event.plain_result(self._get_help_text())

    @fc_group.command("open")
    async def fc_open(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.account_handler.handle_open(event, self._args(event, "open"), group_id, user_id, user_name):
            yield result

    @fc_group.command("me")
    async def fc_me(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.account_handler.handle_me(event, group_id, user_id, user_name):
            yield result

    @fc_group.command("sign")
    async def fc_sign(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.account_handler.handle_sign(event, group_id, user_id, user_name):
            yield result

    @fc_group.command("transfer")
    async def fc_transfer(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.account_handler.handle_transfer(event, self._args(event, "transfer"), group_id, user_id, user_name):
            yield result

    @fc_group.command("rank")
    async def fc_rank(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.admin_handler.handle_rank(event, self._args(event, "rank"), group_id, user_id, user_name):
            yield result

    @fc_group.command("stock")
    async def fc_stock(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.stock_handler.handle(event, self._args(event, "stock"), group_id, user_id, user_name):
            yield result

    @fc_group.command("goods")
    async def fc_goods(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.goods_handler.handle(event, self._args(event, "goods"), group_id, user_id, user_name):
            yield result

    @fc_group.command("admin")
    async def fc_admin(self, event: AstrMessageEvent):
        info = self._route_info(event)
        if not info: return
        group_id, user_id, user_name = info
        async for result in self.admin_handler.handle(event, self._args(event, "admin"), group_id, user_id, user_name):
            yield result

    def _get_help_text(self):
        currency_name = self.config.currency.currency_name
        lines = [
            f"💰 {currency_name}金融中心",
            "━━━━━━━━━━━━━━",
            "  /fc open              开户",
            "  /fc me                我的账户",
            "  /fc sign              每日签到",
            "  /fc transfer <@用户> <金额>  转账",
            "  /fc rank [条数]       财富排行榜",
            "",
            "  /fc stock             股市帮助",
            "  /fc goods             物资帮助",
            "  /fc admin             管理员指令",
            "",
            "  /fc help              显示帮助",
        ]
        return "\n".join(lines)

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

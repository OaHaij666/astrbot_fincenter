"""FinCenter 插件主模块

提供 AstrBot 插件入口，负责配置解析、数据库初始化、
市场引擎生命周期管理和指令路由。
"""
import asyncio
import os
import logging
from typing import Any

from astrbot.api import register, AstrBotEvent

from .config import FinCenterConfig
from .core.database import DB, ChatRewardState, UserAccount, PaidCommand, get_china_time
from .markets.stock import StockMarket
from .markets.goods import GoodsMarket
from .handlers import AccountHandler, StockHandler, GoodsHandler, AdminHandler
from .utils import plotter
from migrations.migrate import migrate, set_paths as set_migrate_paths

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@register("FinCenter")
class FinCenterPlugin:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._raw_config = ctx.config

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
        self.fonts_dir = os.path.join(self.assets_dir, 'fonts')

        for d in [self.data_dir, self.assets_dir, self.cache_dir, self.fonts_dir]:
            os.makedirs(d, exist_ok=True)

        plotter.set_paths(base_dir=self.base_dir)
        set_migrate_paths(base_dir=self.base_dir)

    def _setup_config(self):
        """使用 FinCenterConfig 解析配置，替代散落的 get() 调用"""
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
        """根据 cross_group_data 配置决定 group_id：跨群共享时统一为 __global__"""
        if self.config.basic.cross_group_data:
            return "__global__"
        return group_id

    def _check_group_allowed(self, group_id: str) -> bool:
        """检查群是否在允许范围内"""
        cfg = self.config.basic
        if not cfg.group_filter_enabled:
            return True
        if cfg.group_whitelist and group_id not in cfg.group_whitelist:
            return False
        if cfg.group_blacklist and group_id in cfg.group_blacklist:
            return False
        return True

    def _process_chat_reward(self, group_id: str, user_id: str, user_name: str):
        """处理发言奖励（同步，在 on_event 中调用）"""
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
        """检查是否为收费指令，返回扣费提示消息；非收费指令返回 None"""
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

    async def on_event(self, event: AstrBotEvent):
        message = event.message_obj.message
        if not message or not isinstance(message, str):
            return

        message = message.strip()

        group_id = event.get_group_id() or "default"
        user_id = event.get_sender_id()
        user_name = event.get_sender_name() or user_id

        # 群过滤检查
        if not self._check_group_allowed(group_id):
            return

        # 跨群数据
        group_id = self._resolve_group_id(group_id)

        # 非 /fc 指令：处理发言奖励和收费指令
        if not message.startswith("/fc"):
            self._process_chat_reward(group_id, user_id, user_name)
            paid_msg = self._check_paid_command(message, group_id, user_id)
            if paid_msg:
                yield event.plain_result(paid_msg)
            return

        args = message.split()
        if len(args) < 2:
            yield event.plain_result(self._get_help())
            return

        sub = args[1] if len(args) >= 2 else None

        if sub == "help":
            yield event.plain_result(self._get_help())

        elif sub == "open":
            async for result in self.account_handler.handle_open(event, args, group_id, user_id, user_name):
                yield result

        elif sub == "me":
            async for result in self.account_handler.handle_me(event, group_id, user_id, user_name):
                yield result

        elif sub == "sign":
            async for result in self.account_handler.handle_sign(event, group_id, user_id, user_name):
                yield result

        elif sub == "transfer":
            async for result in self.account_handler.handle_transfer(event, args, group_id, user_id, user_name):
                yield result

        elif sub == "rank":
            async for result in self.admin_handler.handle_rank(event, args, group_id, user_id, user_name):
                yield result

        elif sub == "stock":
            async for result in self.stock_handler.handle(event, args, group_id, user_id, user_name):
                yield result

        elif sub == "goods":
            async for result in self.goods_handler.handle(event, args, group_id, user_id, user_name):
                yield result

        elif sub == "admin":
            async for result in self.admin_handler.handle(event, args, group_id, user_id, user_name):
                yield result

        else:
            yield event.plain_result(self._get_help())

    def _get_help(self):
        currency_name = self.config.currency.currency_name
        currency_icon = self.config.currency.currency_icon
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

    def shutdown(self):
        """优雅关闭所有市场引擎"""
        if self.stock_market:
            self.stock_market.stop()
            logger.info("Stock market stopped")
        if self.goods_market:
            self.goods_market.stop()
            logger.info("Goods market stopped")

    def __del__(self):
        self.shutdown()

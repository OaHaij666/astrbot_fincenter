"""FinCenter 插件入口

AstrBot 要求插件类定义在根 main.py，handler 的 __module__ 才会与框架的
module_path 匹配，从而正确绑定 self。

  - 使用 @filter.command() 平级注册，不使用 command_group
  - html_render 调用签名: html_render(html_content, data_dict, return_url, options)
  - 图片通过 event.image_result() 发送
"""
import os
import sys
import tempfile
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
from src.core.database import DB
from src.services.market_manager import MarketManager
from src.services.rewards import ChatRewardService
from src.services.paid_command import PaidCommandService
from src.services.web_api import FinCenterWebApi
from src.handlers import AccountHandler, StockHandler, GoodsHandler, AdminHandler
from src.utils import plotter
from src.utils.renderer import LocalHtmlRenderer
from src.utils.help_builder import build_main_help_sections, build_main_help_text
from migrations.migrate import migrate, set_paths as set_migrate_paths


@register("FinCenter", "FinCenter Team", "群聊财富中心 - 开户签到股市交易物资贸易", "1.0.0")
class FinCenterPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self._raw_config = config or {}

        self._setup_paths()
        self._setup_config()
        self._setup_database()
        self.reward_service = ChatRewardService(self.db, self.config)
        self.paid_command_service = PaidCommandService(self.db, self.config)
        self.web_api = FinCenterWebApi(self)
        self.web_api.register()
        self.local_renderer = LocalHtmlRenderer()
        self._setup_handlers()
        self._setup_markets()

    # ── 辅助方法 ──────────────────────────────────────────────

    def _extract_raw_group_id(self, event: AstrMessageEvent) -> str:
        """从 unified_msg_origin 提取真实群号，私聊场景回退到 user_id。"""
        origin = getattr(event, "unified_msg_origin", "") or ""
        parts = origin.split(":")
        if len(parts) >= 3 and "Group" in parts[1]:
            return parts[2]
        return str(event.get_sender_id())

    def _extract_group_id(self, event: AstrMessageEvent) -> str:
        """提取账户域 group_id；cross_group_data 只影响金钱/账户数据。"""
        return self._resolve_group_id(self._extract_raw_group_id(event))

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        """从 event 获取发送者昵称"""
        return event.get_sender_name() or str(event.get_sender_id())

    @staticmethod
    def _parse_args(event: AstrMessageEvent) -> list:
        """从 event.message_str 解析出参数列表"""
        return event.message_str.split()

    # ── 初始化 ────────────────────────────────────────────────

    def _setup_paths(self):
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
        self.account_handler = AccountHandler(self, self.html_render)
        self.stock_handler = StockHandler(self, self.html_render)
        self.goods_handler = GoodsHandler(self, self.html_render)
        self.admin_handler = AdminHandler(self, self.html_render)

    def _setup_markets(self):
        self.stock_market = None
        self.goods_market = None
        self.market_manager = MarketManager(self)

        if self.config.stock.stock_enabled:
            self.enable_stock_market(update_config=False)

        if self.config.goods.goods_enabled:
            self.enable_goods_market(update_config=False)

    def enable_stock_market(self, update_config: bool = True):
        return self.market_manager.enable_stock(update_config)

    def disable_stock_market(self, update_config: bool = True):
        return self.market_manager.disable_stock(update_config)

    def enable_goods_market(self, update_config: bool = True):
        return self.market_manager.enable_goods(update_config)

    def disable_goods_market(self, update_config: bool = True):
        return self.market_manager.disable_goods(update_config)

    def _resolve_group_id(self, group_id: str) -> str:
        if self.config.basic.cross_group_data:
            return "__global__"
        return group_id

    def get_stock_binding(self, physical_group_id: str) -> tuple[bool, str]:
        if hasattr(self.db, "get_market_binding"):
            return self.db.get_market_binding(physical_group_id, "stock")
        return True, str(physical_group_id)

    def get_goods_binding(self, physical_group_id: str) -> tuple[bool, str]:
        if hasattr(self.db, "get_market_binding"):
            return self.db.get_market_binding(physical_group_id, "goods")
        return True, str(physical_group_id)

    def get_paid_binding(self, physical_group_id: str) -> tuple[bool, str]:
        physical_group_id = str(physical_group_id)
        if hasattr(self.db, "get_market_binding"):
            enabled, group_id = self.db.get_market_binding(physical_group_id, "paid")
            if not enabled or group_id != physical_group_id:
                return enabled, group_id
        for item in getattr(self.config.paid_cmd, "paid_cmd_group_bindings", []) or []:
            if str(item.get("group_id", "")) == physical_group_id:
                enabled = item.get("enabled", True)
                if isinstance(enabled, str):
                    enabled = enabled.strip().lower() not in ("0", "false", "no", "off", "禁用", "否")
                return bool(enabled), str(item.get("paid_group_id") or physical_group_id)
        return True, physical_group_id

    def set_market_binding(self, physical_group_id: str, module: str, market_group_id: str = None, enabled: bool = True):
        if hasattr(self.db, "set_market_binding"):
            return self.db.set_market_binding(physical_group_id, module, market_group_id, enabled)
        return enabled, str(market_group_id or physical_group_id)

    def _check_group_allowed(self, group_id: str) -> bool:
        cfg = self.config.basic
        if not cfg.group_filter_enabled:
            return True
        if cfg.group_whitelist and group_id not in cfg.group_whitelist:
            return False
        if cfg.group_blacklist and group_id in cfg.group_blacklist:
            return False
        return True

    # ── 图片渲染与发送 ────────────────────────────────────────
    # 渲染策略：优先本地 Playwright → 回退远程 html_render → 回退文字

    async def _render_image_remote(self, html_content, data=None, options=None):
        """使用远程 html_render 渲染"""
        try:
            image_data = await self.html_render(
                html_content,
                data or {},
                False,
                options or {"type": "png"},
            )
            if not image_data:
                return None
            if isinstance(image_data, str):
                return image_data
            elif isinstance(image_data, bytes):
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=self.cache_dir)
                tmp.write(image_data)
                tmp.close()
                return tmp.name
            else:
                logger.warning(f"html_render 返回了意外类型: {type(image_data)}")
                return None
        except Exception as e:
            logger.error(f"远程 html_render 失败: {e}")
            return None

    async def _render_image(self, html_content, data=None, options=None):
        """渲染 HTML 为图片：根据配置选择优先策略，失败自动回退"""
        strategy = self.config.rendering.render_strategy

        if strategy == "local":
            # 优先本地 Playwright，失败回退远程
            local_path = await self.local_renderer.render(html_content, data, options, self.cache_dir)
            if local_path:
                return local_path
            # 回退远程 html_render
            return await self._render_image_remote(html_content, data, options)
        else:
            # 优先远程 html_render，失败回退本地
            remote_path = await self._render_image_remote(html_content, data, options)
            if remote_path:
                return remote_path
            # 回退本地 Playwright
            return await self.local_renderer.render(html_content, data, options, self.cache_dir)

    # ── 命令注册 ──────────────────────────────────────────────
    # 对齐参考项目: 使用 @filter.command() 平级注册，不使用 command_group
    # 所有子命令在 /fc 内部通过 message_str 解析路由

    @filter.command("fc", alias={"财富中心", "fincenter"})
    async def fc(self, event: AstrMessageEvent):
        """财富中心 - 开户/签到/股市/物资/管理"""
        raw_group_id = self._extract_raw_group_id(event)
        group_id = self._resolve_group_id(raw_group_id)
        stock_enabled, stock_group_id = self.get_stock_binding(raw_group_id)
        goods_enabled, goods_group_id = self.get_goods_binding(raw_group_id)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        args = self._parse_args(event)

        # args[0] = "fc", args[1] = 子模块, args[2] = 子命令, ...
        module = args[1] if len(args) >= 2 else None

        if module is None:
            # 显示总帮助
            result = plotter.render_help_html(
                title="💰 财富中心",
                sections=build_main_help_sections(),
                tips=['先 /fc open 开户，再 /fc sign 签到领币'],
            )
            if result:
                html_content, data = result
                image_path = await self._render_image(html_content, data)
                if image_path:
                    yield event.image_result(image_path)
                    return
            yield event.plain_result(self._get_main_help_text())
            return

        # ── 账户指令 ──
        if module == "open":
            async for result in self.account_handler.handle_open(event, args, group_id, user_id, user_name):
                yield result
        elif module == "me":
            async for result in self.account_handler.handle_me(event, group_id, user_id, user_name, stock_group_id, goods_group_id, stock_enabled, goods_enabled):
                yield result
        elif module == "sign":
            async for result in self.account_handler.handle_sign(event, group_id, user_id, user_name):
                yield result
        elif module == "transfer":
            async for result in self.account_handler.handle_transfer(event, args, group_id, user_id, user_name):
                yield result
        elif module == "rank":
            async for result in self.admin_handler.handle_rank(event, args, raw_group_id, group_id, user_id, user_name):
                yield result

        # ── 股市指令 ──
        elif module == "stock":
            async for result in self.stock_handler.handle(event, args, stock_group_id, group_id, user_id, user_name, stock_enabled):
                yield result

        # ── 物资指令 ──
        elif module == "goods":
            async for result in self.goods_handler.handle(event, args, goods_group_id, group_id, user_id, user_name, goods_enabled):
                yield result

        # ── 管理员指令 ──
        elif module == "admin":
            async for result in self.admin_handler.handle(event, args, raw_group_id, group_id, user_id, user_name):
                yield result

        else:
            yield event.plain_result(f"未知指令: {module}\n输入 /fc 查看帮助")

    # ── 聊天奖励（事件监听）──────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=200)
    async def on_group_message(self, event: AstrMessageEvent):
        """群消息事件：处理聊天奖励和付费指令拦截。

        priority=200 让本 handler 在其他插件命令 handler 之前执行，
        命中付费指令时先扣费再放行；插件抛异常会触发 ``on_plugin_error``，
        我们的 hook 会读取 ``fc_paid_record`` 并退款。
        """
        raw_group_id = self._extract_raw_group_id(event)
        group_id = self._resolve_group_id(raw_group_id)
        paid_enabled, paid_group_id = self.get_paid_binding(raw_group_id)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)

        if not self._check_group_allowed(raw_group_id):
            return

        # 聊天奖励
        self.reward_service.process(group_id, user_id, user_name)

        # 付费指令检查
        message = event.message_str.strip()
        if not message:
            return
        # 跳过本插件自己的命令，避免误扣费
        if message.startswith(("fc", "/fc", "财富中心", "fincenter")):
            return

        if not paid_enabled:
            return

        try_deduct = getattr(self.paid_command_service, "try_deduct", None)
        if not try_deduct:
            logger.warning("PaidCommandService 缺少 try_deduct，请确认 src/services/paid_command.py 已更新")
            return

        status, reply, record = try_deduct(
            message, paid_group_id, group_id, user_id
        )
        if status == "charged" and record is not None:
            event.set_extra("fc_paid_record", record)
            if reply:
                yield event.plain_result(reply)
            return  # 不 stop_event，让事件继续传播给其他插件
        if status in ("insufficient", "no_account") and reply:
            yield event.plain_result(reply)
            event.stop_event()  # 余额不足，阻止事件继续传播
            return

    @filter.on_plugin_error()
    async def on_plugin_error(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        handler_name: str,
        error: Exception,
        traceback_text: str,
    ):
        """目标插件 handler 抛异常时退款。"""
        record = event.get_extra("fc_paid_record")
        if not record:
            return
        # 自身报错不退（避免循环）
        if plugin_name == "FinCenter":
            return
        try:
            ok = self.paid_command_service.refund(record)
        except Exception as e:
            logger.warning(f"付费指令退款异常: {e}")
            return
        # 清除 extra，避免重复退款
        event.set_extra("fc_paid_record", None)
        if ok:
            cost = record.get("cost", 0)
            currency_icon = self.config.currency.currency_icon
            try:
                event.set_result(event.plain_result(
                    f"⚠️ 插件调用失败，已退还 {currency_icon}{float(cost):.2f}"
                ))
            except Exception:
                pass

    # ── 生命周期 ──────────────────────────────────────────────

    async def terminate(self):
        self.market_manager.stop_all()
        await self.local_renderer.close()

    def __del__(self):
        try:
            self.market_manager.stop_all()
        except Exception:
            pass

    # ── 纯文本帮助回退 ────────────────────────────────────────

    def _get_main_help_text(self):
        return build_main_help_text()

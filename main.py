"""FinCenter 插件入口

AstrBot 要求插件类定义在根 main.py，handler 的 __module__ 才会与框架的
module_path 匹配，从而正确绑定 self。

  - 使用 @filter.command() 平级注册，不使用 command_group
  - html_render 调用签名: html_render(html_content, data_dict, return_url, options)
  - 图片通过 event.image_result() 发送
"""
import base64
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

    # ── 图片渲染与发送 ────────────────────────────────────────
    # 渲染策略：优先本地 Playwright → 回退远程 html_render → 回退文字
    # 通过 event.image_result(文件路径) 发送，框架自动处理文件读取和上传
    # 必须用 yield 返回结果，否则框架不知道已响应，会继续走 LLM

    _playwright_instance = None
    _playwright_browser = None

    @classmethod
    async def _get_playwright_browser(cls):
        """懒加载 Playwright 浏览器实例（全局单例）"""
        if cls._playwright_browser and cls._playwright_browser.is_connected():
            return cls._playwright_browser
        try:
            from playwright.async_api import async_playwright
            if cls._playwright_instance is None:
                cls._playwright_instance = await async_playwright().start()
            if cls._playwright_browser is None or not cls._playwright_browser.is_connected():
                cls._playwright_browser = await cls._playwright_instance.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-gpu'],
                )
            return cls._playwright_browser
        except Exception as e:
            logger.warning(f"Playwright 不可用: {e}")
            return None

    async def _render_image_local(self, html_content, data=None, options=None):
        """使用本地 Playwright 渲染 HTML 为图片，返回文件路径或 None"""
        browser = await self._get_playwright_browser()
        if not browser:
            return None

        import jinja2
        page = None
        try:
            # Jinja2 渲染
            if data:
                tmpl = jinja2.Template(html_content)
                rendered_html = tmpl.render(**data)
            else:
                rendered_html = html_content

            page = await browser.new_page(viewport={"width": 500, "height": 800})
            await page.set_content(rendered_html, wait_until="networkidle", timeout=10000)

            # 等待内容渲染
            await page.wait_for_timeout(300)

            # 获取 body 实际尺寸，精确裁剪到内容边界
            body_size = await page.evaluate("""() => {
                const body = document.body;
                const html = document.documentElement;
                return {
                    width: Math.min(Math.max(body.scrollWidth, body.offsetWidth), 600),
                    height: Math.max(body.scrollHeight, body.offsetHeight)
                };
            }""")

            # 截图选项 - 用 clip 精确裁剪，避免右侧空白
            opts = options or {}
            screenshot_opts = {
                "type": opts.get("type", "png"),
                "clip": {
                    "x": 0,
                    "y": 0,
                    "width": body_size["width"],
                    "height": body_size["height"],
                },
            }
            if opts.get("quality"):
                screenshot_opts["quality"] = opts["quality"]

            img_bytes = await page.screenshot(**screenshot_opts)

            # 保存到临时文件
            suffix = ".jpg" if screenshot_opts["type"] == "jpeg" else ".png"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=self.cache_dir)
            tmp.write(img_bytes)
            tmp.close()
            return tmp.name

        except Exception as e:
            logger.warning(f"本地 Playwright 渲染失败: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _render_image(self, html_content, data=None, options=None):
        """渲染 HTML 为图片：优先本地 Playwright，失败回退远程 html_render"""
        # 1. 尝试本地 Playwright
        local_path = await self._render_image_local(html_content, data, options)
        if local_path:
            return local_path

        # 2. 回退远程 html_render
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
            logger.error(f"远程 html_render 也失败: {e}")
            return None

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

            user.add_balance(cfg.chat_reward_amount)
            user.add_earned(cfg.chat_reward_amount)
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

            user.sub_balance(paid_cmd.cost)
            user.add_spent(paid_cmd.cost)

            if cfg.paid_cmd_deduct_msg:
                return cfg.paid_cmd_deduct_msg.format(
                    cost=paid_cmd.cost,
                    currency=self.config.currency.currency_name,
                    balance=user.balance,
                )

        return None

    # ── 命令注册 ──────────────────────────────────────────────
    # 对齐参考项目: 使用 @filter.command() 平级注册，不使用 command_group
    # 所有子命令在 /fc 内部通过 message_str 解析路由

    @filter.command("fc", alias={"财富中心", "fincenter"})
    async def fc(self, event: AstrMessageEvent):
        """财富中心 - 开户/签到/股市/物资/管理"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)
        args = self._parse_args(event)

        # args[0] = "fc", args[1] = 子模块, args[2] = 子命令, ...
        module = args[1] if len(args) >= 2 else None

        if module is None:
            # 显示总帮助
            result = plotter.render_help_html(
                title="💰 财富中心",
                sections=[
                    {
                        'section_name': '👤 账户',
                        'commands': [
                            {'cmd': '/fc open', 'desc': '开户'},
                            {'cmd': '/fc me', 'desc': '我的账户'},
                            {'cmd': '/fc sign', 'desc': '每日签到'},
                            {'cmd': '/fc transfer <@用户> <金额>', 'desc': '转账'},
                            {'cmd': '/fc rank [条数]', 'desc': '财富排行榜'},
                        ],
                    },
                    {
                        'section_name': '📈 股市',
                        'commands': [
                            {'cmd': '/fc stock market', 'desc': '股市总览'},
                            {'cmd': '/fc stock buy <代码> <数量>', 'desc': '买入股票'},
                            {'cmd': '/fc stock sell <代码> <数量>', 'desc': '卖出股票'},
                            {'cmd': '/fc stock assets', 'desc': '我的持仓'},
                            {'cmd': '/fc stock kline <代码> [条数]', 'desc': 'K线图'},
                            {'cmd': '/fc stock news', 'desc': '市场新闻'},
                        ],
                    },
                    {
                        'section_name': '📦 物资',
                        'commands': [
                            {'cmd': '/fc goods market', 'desc': '物资市场'},
                            {'cmd': '/fc goods buy <ID> <数量>', 'desc': '买入物资'},
                            {'cmd': '/fc goods sell <ID> <数量>', 'desc': '卖出物资'},
                            {'cmd': '/fc goods backpack', 'desc': '我的背包'},
                        ],
                    },
                ],
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
            async for result in self.account_handler.handle_me(event, group_id, user_id, user_name):
                yield result
        elif module == "sign":
            async for result in self.account_handler.handle_sign(event, group_id, user_id, user_name):
                yield result
        elif module == "transfer":
            async for result in self.account_handler.handle_transfer(event, args, group_id, user_id, user_name):
                yield result
        elif module == "rank":
            async for result in self.admin_handler.handle_rank(event, args, group_id, user_id, user_name):
                yield result

        # ── 股市指令 ──
        elif module == "stock":
            async for result in self.stock_handler.handle(event, args, group_id, user_id, user_name):
                yield result

        # ── 物资指令 ──
        elif module == "goods":
            async for result in self.goods_handler.handle(event, args, group_id, user_id, user_name):
                yield result

        # ── 管理员指令 ──
        elif module == "admin":
            async for result in self.admin_handler.handle(event, args, group_id, user_id, user_name):
                yield result

        else:
            yield event.plain_result(f"未知指令: {module}\n输入 /fc 查看帮助")

    # ── 聊天奖励（事件监听）──────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """群消息事件：处理聊天奖励和付费指令"""
        group_id = self._extract_group_id(event)
        user_id = str(event.get_sender_id())
        user_name = self._get_user_name(event)

        if not self._check_group_allowed(group_id):
            return

        # 聊天奖励
        self._process_chat_reward(group_id, user_id, user_name)

        # 付费指令检查
        message = event.message_str.strip()
        paid_msg = self._check_paid_command(message, group_id, user_id)
        if paid_msg:
            yield event.plain_result(paid_msg)

    # ── 生命周期 ──────────────────────────────────────────────

    async def terminate(self):
        if self.stock_market:
            self.stock_market.stop()
            logger.info("Stock market stopped")
        if self.goods_market:
            self.goods_market.stop()
            logger.info("Goods market stopped")
        # 关闭 Playwright
        if self._playwright_browser:
            try:
                await self._playwright_browser.close()
            except Exception:
                pass
            self.__class__._playwright_browser = None
        if self._playwright_instance:
            try:
                await self._playwright_instance.stop()
            except Exception:
                pass
            self.__class__._playwright_instance = None

    def __del__(self):
        if self.stock_market:
            self.stock_market.stop()
        if self.goods_market:
            self.goods_market.stop()

    # ── 纯文本帮助回退 ────────────────────────────────────────

    def _get_main_help_text(self):
        lines = [
            "💰 财富中心",
            "━━━━━━━━━━━━━━",
            "👤 账户:",
            "  /fc open                    开户",
            "  /fc me                      我的账户",
            "  /fc sign                    每日签到",
            "  /fc transfer <@用户> <金额>   转账",
            "  /fc rank [条数]              财富排行榜",
            "",
            "📈 股市:",
            "  /fc stock market            股市总览",
            "  /fc stock buy <代码> <数量>   买入",
            "  /fc stock sell <代码> <数量>  卖出",
            "  /fc stock assets            我的持仓",
            "  /fc stock kline <代码> [条数] K线图",
            "  /fc stock news              市场新闻",
            "",
            "📦 物资:",
            "  /fc goods market            物资市场",
            "  /fc goods buy <ID> <数量>    买入物资",
            "  /fc goods sell <ID> <数量>   卖出物资",
            "  /fc goods backpack          我的背包",
        ]
        return "\n".join(lines)

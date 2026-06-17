"""FinCenter 插件配置模块

提供类型安全的配置访问，与 _conf_schema.json 的嵌套结构严格对齐。
所有配置项通过 dataclass 定义，支持从 AstrBot 传入的嵌套字典构建。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List


def _normalize_id_list(value: Any) -> List[str]:
    """将配置中的 ID 列表规范化为可直接匹配 event.get_sender_id() 的字符串列表。

    AstrBot 配置面板/手工配置里可能出现数字、带空格字符串、逗号/换行分隔字符串，
    甚至复制 @ 消息后带 CQ/尖括号格式；这里统一提取为纯 ID 字符串，避免管理员判断失效。
    """
    if value is None:
        return []

    raw_items = value if isinstance(value, (list, tuple, set)) else [value]
    result: List[str] = []
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue

        parts = re.split(r"[\s,，;；]+", text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            digit_groups = re.findall(r"\d+", part)
            if digit_groups:
                result.extend(digit_groups)
            else:
                result.append(part)

    return list(dict.fromkeys(result))


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
    return bool(value)


@dataclass
class BasicConfig:
    """基础设置"""
    admin_ids: List[str] = field(default_factory=list)
    cross_group_data: bool = False
    group_filter_enabled: bool = False
    group_whitelist: List[str] = field(default_factory=list)
    group_blacklist: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> BasicConfig:
        if not data:
            return cls()
        return cls(
            admin_ids=_normalize_id_list(data.get("admin_ids", [])),
            cross_group_data=_to_bool(data.get("cross_group_data", False)),
            group_filter_enabled=_to_bool(data.get("group_filter_enabled", False)),
            group_whitelist=list(data.get("group_whitelist", [])),
            group_blacklist=list(data.get("group_blacklist", [])),
        )


@dataclass
class CurrencyConfig:
    """货币设置"""
    currency_name: str = "金币"
    currency_icon: str = "💰"
    initial_balance: float = 1000.0
    open_account_cost: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> CurrencyConfig:
        if not data:
            return cls()
        try:
            initial_balance = float(data.get("initial_balance", 1000.0))
        except (ValueError, TypeError):
            initial_balance = 1000.0
        try:
            open_account_cost = float(data.get("open_account_cost", 0.0))
        except (ValueError, TypeError):
            open_account_cost = 0.0
        return cls(
            currency_name=str(data.get("currency_name", "金币")),
            currency_icon=str(data.get("currency_icon", "💰")),
            initial_balance=initial_balance,
            open_account_cost=open_account_cost,
        )


@dataclass
class SigninConfig:
    """签到设置"""
    signin_enabled: bool = True
    signin_reward_base: float = 100.0
    signin_reward_var: float = 50.0
    signin_consecutive_bonus: float = 20.0
    signin_max_consecutive: int = 7

    @classmethod
    def from_dict(cls, data: dict) -> SigninConfig:
        if not data:
            return cls()
        try:
            signin_reward_base = float(data.get("signin_reward_base", 100.0))
        except (ValueError, TypeError):
            signin_reward_base = 100.0
        try:
            signin_reward_var = float(data.get("signin_reward_var", 50.0))
        except (ValueError, TypeError):
            signin_reward_var = 50.0
        try:
            signin_consecutive_bonus = float(data.get("signin_consecutive_bonus", 20.0))
        except (ValueError, TypeError):
            signin_consecutive_bonus = 20.0
        try:
            signin_max_consecutive = int(data.get("signin_max_consecutive", 7))
        except (ValueError, TypeError):
            signin_max_consecutive = 7
        return cls(
            signin_enabled=_to_bool(data.get("signin_enabled", True)),
            signin_reward_base=signin_reward_base,
            signin_reward_var=signin_reward_var,
            signin_consecutive_bonus=signin_consecutive_bonus,
            signin_max_consecutive=signin_max_consecutive,
        )


@dataclass
class ChatRewardConfig:
    """发言奖励设置"""
    chat_reward_enabled: bool = True
    chat_reward_amount: float = 1.0
    chat_reward_cooldown: int = 60
    chat_reward_daily_limit: int = 50

    @classmethod
    def from_dict(cls, data: dict) -> ChatRewardConfig:
        if not data:
            return cls()
        try:
            chat_reward_amount = float(data.get("chat_reward_amount", 1.0))
        except (ValueError, TypeError):
            chat_reward_amount = 1.0
        try:
            chat_reward_cooldown = int(data.get("chat_reward_cooldown", 60))
        except (ValueError, TypeError):
            chat_reward_cooldown = 60
        try:
            chat_reward_daily_limit = int(data.get("chat_reward_daily_limit", 50))
        except (ValueError, TypeError):
            chat_reward_daily_limit = 50
        return cls(
            chat_reward_enabled=_to_bool(data.get("chat_reward_enabled", True)),
            chat_reward_amount=chat_reward_amount,
            chat_reward_cooldown=chat_reward_cooldown,
            chat_reward_daily_limit=chat_reward_daily_limit,
        )


@dataclass
class StockConfig:
    """股市设置"""
    stock_enabled: bool = True
    stock_companies: List[Dict[str, Any]] = field(default_factory=list)
    stock_volatility: float = 0.02
    stock_update_interval: int = 300
    stock_fee_rate: float = 0.001
    stock_trading_hours: bool = False
    stock_trend_enabled: bool = True
    stock_tech_analysis_enabled: bool = True
    stock_kline_candles: int = 50
    stock_font: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> StockConfig:
        if not data:
            return cls()
        try:
            stock_volatility = float(data.get("stock_volatility", 0.02))
        except (ValueError, TypeError):
            stock_volatility = 0.02
        try:
            stock_update_interval = int(data.get("stock_update_interval", 300))
        except (ValueError, TypeError):
            stock_update_interval = 300
        try:
            stock_fee_rate = float(data.get("stock_fee_rate", 0.001))
        except (ValueError, TypeError):
            stock_fee_rate = 0.001
        try:
            stock_kline_candles = int(data.get("stock_kline_candles", 50))
        except (ValueError, TypeError):
            stock_kline_candles = 50
        return cls(
            stock_enabled=_to_bool(data.get("stock_enabled", True)),
            stock_companies=list(data.get("stock_companies", [])),
            stock_volatility=stock_volatility,
            stock_update_interval=stock_update_interval,
            stock_fee_rate=stock_fee_rate,
            stock_trading_hours=_to_bool(data.get("stock_trading_hours", False)),
            stock_trend_enabled=_to_bool(data.get("stock_trend_enabled", True)),
            stock_tech_analysis_enabled=_to_bool(data.get("stock_tech_analysis_enabled", True)),
            stock_kline_candles=stock_kline_candles,
            stock_font=str(data.get("stock_font", "")),
        )


@dataclass
class StockNewsConfig:
    """股市新闻设置"""
    stock_news_enabled: bool = True
    stock_news_source: str = "template"
    stock_news_trigger_prob: float = 0.3
    stock_news_broadcast: bool = True
    stock_news_history_count: int = 10
    stock_news_provider_id: str = ""
    stock_llm_prompt_template: str = ""
    stock_news_prob_major_positive: float = 0.05
    stock_news_prob_positive: float = 0.15
    stock_news_prob_slight_positive: float = 0.20
    stock_news_prob_neutral: float = 0.25
    stock_news_prob_slight_negative: float = 0.20
    stock_news_prob_negative: float = 0.12
    stock_news_prob_major_negative: float = 0.03
    stock_news_prob_volatility: float = 0.10

    @classmethod
    def from_dict(cls, data: dict) -> StockNewsConfig:
        if not data:
            return cls()
        try:
            stock_news_trigger_prob = float(data.get("stock_news_trigger_prob", 0.3))
        except (ValueError, TypeError):
            stock_news_trigger_prob = 0.3
        try:
            stock_news_history_count = int(data.get("stock_news_history_count", 10))
        except (ValueError, TypeError):
            stock_news_history_count = 10
        try:
            stock_news_prob_major_positive = float(data.get("stock_news_prob_major_positive", 0.05))
        except (ValueError, TypeError):
            stock_news_prob_major_positive = 0.05
        try:
            stock_news_prob_positive = float(data.get("stock_news_prob_positive", 0.15))
        except (ValueError, TypeError):
            stock_news_prob_positive = 0.15
        try:
            stock_news_prob_slight_positive = float(data.get("stock_news_prob_slight_positive", 0.20))
        except (ValueError, TypeError):
            stock_news_prob_slight_positive = 0.20
        try:
            stock_news_prob_neutral = float(data.get("stock_news_prob_neutral", 0.25))
        except (ValueError, TypeError):
            stock_news_prob_neutral = 0.25
        try:
            stock_news_prob_slight_negative = float(data.get("stock_news_prob_slight_negative", 0.20))
        except (ValueError, TypeError):
            stock_news_prob_slight_negative = 0.20
        try:
            stock_news_prob_negative = float(data.get("stock_news_prob_negative", 0.12))
        except (ValueError, TypeError):
            stock_news_prob_negative = 0.12
        try:
            stock_news_prob_major_negative = float(data.get("stock_news_prob_major_negative", 0.03))
        except (ValueError, TypeError):
            stock_news_prob_major_negative = 0.03
        try:
            stock_news_prob_volatility = float(data.get("stock_news_prob_volatility", 0.10))
        except (ValueError, TypeError):
            stock_news_prob_volatility = 0.10
        return cls(
            stock_news_enabled=_to_bool(data.get("stock_news_enabled", True)),
            stock_news_source=str(data.get("stock_news_source", "template")),
            stock_news_trigger_prob=stock_news_trigger_prob,
            stock_news_broadcast=_to_bool(data.get("stock_news_broadcast", True)),
            stock_news_history_count=stock_news_history_count,
            stock_news_provider_id=str(data.get("stock_news_provider_id", "")),
            stock_llm_prompt_template=str(data.get("stock_llm_prompt_template", "")),
            stock_news_prob_major_positive=stock_news_prob_major_positive,
            stock_news_prob_positive=stock_news_prob_positive,
            stock_news_prob_slight_positive=stock_news_prob_slight_positive,
            stock_news_prob_neutral=stock_news_prob_neutral,
            stock_news_prob_slight_negative=stock_news_prob_slight_negative,
            stock_news_prob_negative=stock_news_prob_negative,
            stock_news_prob_major_negative=stock_news_prob_major_negative,
            stock_news_prob_volatility=stock_news_prob_volatility,
        )

    def to_dict(self) -> dict:
        """导出为原始字典，供 StockNewsGenerator 读取概率配置"""
        return {
            "stock_news_prob_major_positive": self.stock_news_prob_major_positive,
            "stock_news_prob_positive": self.stock_news_prob_positive,
            "stock_news_prob_slight_positive": self.stock_news_prob_slight_positive,
            "stock_news_prob_neutral": self.stock_news_prob_neutral,
            "stock_news_prob_slight_negative": self.stock_news_prob_slight_negative,
            "stock_news_prob_negative": self.stock_news_prob_negative,
            "stock_news_prob_major_negative": self.stock_news_prob_major_negative,
            "stock_news_prob_volatility": self.stock_news_prob_volatility,
            "stock_news_source": self.stock_news_source,
            "stock_news_provider_id": self.stock_news_provider_id,
            "stock_news_history_count": self.stock_news_history_count,
            "stock_llm_prompt_template": self.stock_llm_prompt_template,
        }


@dataclass
class GoodsConfig:
    """物资系统设置"""
    goods_enabled: bool = True
    goods_refresh_interval: int = 86400
    goods_price_volatility: float = 0.1
    goods_user_trade_enabled: bool = True
    goods_user_trade_tax: float = 0.05

    @classmethod
    def from_dict(cls, data: dict) -> GoodsConfig:
        if not data:
            return cls()
        try:
            goods_refresh_interval = int(data.get("goods_refresh_interval", 86400))
        except (ValueError, TypeError):
            goods_refresh_interval = 86400
        try:
            goods_price_volatility = float(data.get("goods_price_volatility", 0.1))
        except (ValueError, TypeError):
            goods_price_volatility = 0.1
        try:
            goods_user_trade_tax = float(data.get("goods_user_trade_tax", 0.05))
        except (ValueError, TypeError):
            goods_user_trade_tax = 0.05
        return cls(
            goods_enabled=_to_bool(data.get("goods_enabled", True)),
            goods_refresh_interval=goods_refresh_interval,
            goods_price_volatility=goods_price_volatility,
            goods_user_trade_enabled=_to_bool(data.get("goods_user_trade_enabled", True)),
            goods_user_trade_tax=goods_user_trade_tax,
        )


@dataclass
class PaidCmdConfig:
    """收费指令设置"""
    paid_cmd_enabled: bool = False
    paid_cmd_default_cost: float = 50.0
    paid_cmd_insufficient_msg: str = ""
    paid_cmd_deduct_msg: str = ""
    paid_cmd_ignore_admin: bool = True
    paid_cmd_prefixes: List[str] = field(default_factory=lambda: ["/"])

    @classmethod
    def from_dict(cls, data: dict) -> PaidCmdConfig:
        if not data:
            return cls()
        try:
            paid_cmd_default_cost = float(data.get("paid_cmd_default_cost", 50.0))
        except (ValueError, TypeError):
            paid_cmd_default_cost = 50.0
        return cls(
            paid_cmd_enabled=_to_bool(data.get("paid_cmd_enabled", False)),
            paid_cmd_default_cost=paid_cmd_default_cost,
            paid_cmd_insufficient_msg=str(data.get("paid_cmd_insufficient_msg",
                "💸 余额不足！执行该指令需要 {cost} {currency}，你当前余额为 {balance} {currency}。")),
            paid_cmd_deduct_msg=str(data.get("paid_cmd_deduct_msg", "")),
            paid_cmd_ignore_admin=_to_bool(data.get("paid_cmd_ignore_admin", True)),
            paid_cmd_prefixes=list(data.get("paid_cmd_prefixes", ["/"])),
        )


@dataclass
class RenderingConfig:
    """图片渲染设置"""
    render_strategy: str = "local"  # "local"=本地Playwright优先, "remote"=远程html_render优先

    @classmethod
    def from_dict(cls, data: dict) -> RenderingConfig:
        if not data:
            return cls()
        return cls(
            render_strategy=str(data.get("render_strategy", "local"))
        )


@dataclass
class FinCenterConfig:
    """FinCenter 插件完整配置

    与 _conf_schema.json 的嵌套结构严格对齐。
    通过 from_dict() 从 AstrBot 传入的原始配置字典构建。
    """
    basic: BasicConfig = field(default_factory=BasicConfig)
    currency: CurrencyConfig = field(default_factory=CurrencyConfig)
    signin: SigninConfig = field(default_factory=SigninConfig)
    chat_reward: ChatRewardConfig = field(default_factory=ChatRewardConfig)
    stock: StockConfig = field(default_factory=StockConfig)
    stock_news: StockNewsConfig = field(default_factory=StockNewsConfig)
    goods: GoodsConfig = field(default_factory=GoodsConfig)
    paid_cmd: PaidCmdConfig = field(default_factory=PaidCmdConfig)
    rendering: RenderingConfig = field(default_factory=RenderingConfig)

    @classmethod
    def from_dict(cls, raw: dict) -> FinCenterConfig:
        """从 AstrBot 传入的原始配置字典构建配置对象

        按嵌套节读取，与 _conf_schema.json 结构对齐。
        """
        def _section(raw: dict, key: str) -> dict:
            val = raw.get(key, {})
            return val if isinstance(val, dict) else {}

        return cls(
            basic=BasicConfig.from_dict(_section(raw, "basic")),
            currency=CurrencyConfig.from_dict(_section(raw, "currency")),
            signin=SigninConfig.from_dict(_section(raw, "signin")),
            chat_reward=ChatRewardConfig.from_dict(_section(raw, "chat_reward")),
            stock=StockConfig.from_dict(_section(raw, "stock")),
            stock_news=StockNewsConfig.from_dict(_section(raw, "stock_news")),
            goods=GoodsConfig.from_dict(_section(raw, "goods")),
            paid_cmd=PaidCmdConfig.from_dict(_section(raw, "paid_cmd")),
            rendering=RenderingConfig.from_dict(_section(raw, "rendering")),
        )

    # ---- 便捷属性 ----

    @property
    def admin_id_set(self) -> set:
        return set(self.basic.admin_ids)

    @property
    def currency_name(self) -> str:
        return self.currency.currency_name

    @property
    def currency_icon(self) -> str:
        return self.currency.currency_icon

    @property
    def initial_balance(self) -> float:
        return self.currency.initial_balance

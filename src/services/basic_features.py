"""基础功能组配置。

基础功能组覆盖货币/开户、签到、发言奖励这些直接影响账户体验的参数。
配置持久化在插件原始配置的 ``basic_feature_groups`` 列表中，群绑定复用
market_group_bindings，module 为 ``basic``。
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace


DEFAULT_GROUP_ID = "default"


def _to_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
    return bool(value)


def _to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def default_group(config) -> dict:
    return {
        "group_id": DEFAULT_GROUP_ID,
        "currency": {
            "currency_name": config.currency.currency_name,
            "currency_icon": config.currency.currency_icon,
            "initial_balance": float(config.currency.initial_balance),
            "open_account_cost": float(config.currency.open_account_cost),
        },
        "signin": {
            "signin_enabled": bool(config.signin.signin_enabled),
            "signin_reward_base": float(config.signin.signin_reward_base),
            "signin_reward_var": float(config.signin.signin_reward_var),
            "signin_consecutive_bonus": float(config.signin.signin_consecutive_bonus),
            "signin_max_consecutive": int(config.signin.signin_max_consecutive),
        },
        "chat_reward": {
            "chat_reward_enabled": bool(config.chat_reward.chat_reward_enabled),
            "chat_reward_amount": float(config.chat_reward.chat_reward_amount),
            "chat_reward_cooldown": int(config.chat_reward.chat_reward_cooldown),
            "chat_reward_daily_limit": int(config.chat_reward.chat_reward_daily_limit),
        },
    }


def normalize_group(raw: dict | None, config, group_id: str | None = None) -> dict:
    base = default_group(config)
    raw = raw if isinstance(raw, dict) else {}
    if group_id is None:
        group_id = str(raw.get("group_id") or DEFAULT_GROUP_ID).strip() or DEFAULT_GROUP_ID
    base["group_id"] = group_id

    currency = raw.get("currency", {}) if isinstance(raw.get("currency", {}), dict) else {}
    signin = raw.get("signin", {}) if isinstance(raw.get("signin", {}), dict) else {}
    chat_reward = raw.get("chat_reward", {}) if isinstance(raw.get("chat_reward", {}), dict) else {}

    base["currency"].update({
        "currency_name": str(currency.get("currency_name", base["currency"]["currency_name"])),
        "currency_icon": str(currency.get("currency_icon", base["currency"]["currency_icon"])),
        "initial_balance": _to_float(currency.get("initial_balance"), base["currency"]["initial_balance"]),
        "open_account_cost": _to_float(currency.get("open_account_cost"), base["currency"]["open_account_cost"]),
    })
    base["signin"].update({
        "signin_enabled": _to_bool(signin.get("signin_enabled"), base["signin"]["signin_enabled"]),
        "signin_reward_base": _to_float(signin.get("signin_reward_base"), base["signin"]["signin_reward_base"]),
        "signin_reward_var": _to_float(signin.get("signin_reward_var"), base["signin"]["signin_reward_var"]),
        "signin_consecutive_bonus": _to_float(signin.get("signin_consecutive_bonus"), base["signin"]["signin_consecutive_bonus"]),
        "signin_max_consecutive": _to_int(signin.get("signin_max_consecutive"), base["signin"]["signin_max_consecutive"]),
    })
    base["chat_reward"].update({
        "chat_reward_enabled": _to_bool(chat_reward.get("chat_reward_enabled"), base["chat_reward"]["chat_reward_enabled"]),
        "chat_reward_amount": _to_float(chat_reward.get("chat_reward_amount"), base["chat_reward"]["chat_reward_amount"]),
        "chat_reward_cooldown": _to_int(chat_reward.get("chat_reward_cooldown"), base["chat_reward"]["chat_reward_cooldown"]),
        "chat_reward_daily_limit": _to_int(chat_reward.get("chat_reward_daily_limit"), base["chat_reward"]["chat_reward_daily_limit"]),
    })
    return base


def list_groups(raw_config, config) -> list[dict]:
    rows = []
    seen = set()
    for item in raw_config.get("basic_feature_groups", []) or []:
        group = normalize_group(item, config)
        if group["group_id"] and group["group_id"] not in seen:
            rows.append(group)
            seen.add(group["group_id"])
    if DEFAULT_GROUP_ID not in seen:
        rows.insert(0, default_group(config))
    return rows


def get_group(raw_config, config, group_id: str | None) -> dict:
    group_id = str(group_id or DEFAULT_GROUP_ID).strip() or DEFAULT_GROUP_ID
    for group in list_groups(raw_config, config):
        if group["group_id"] == group_id:
            return group
    fallback = default_group(config)
    fallback["group_id"] = group_id
    return fallback


def upsert_group(raw_config, config, group: dict) -> dict:
    normalized = normalize_group(group, config)
    rows = [g for g in list_groups(raw_config, config) if g["group_id"] != normalized["group_id"]]
    rows.append(normalized)
    raw_config["basic_feature_groups"] = rows
    return normalized


def remove_group(raw_config, group_id: str) -> bool:
    group_id = str(group_id or "").strip()
    if not group_id or group_id == DEFAULT_GROUP_ID:
        return False
    rows = raw_config.get("basic_feature_groups", []) or []
    kept = [g for g in rows if str(g.get("group_id", "")).strip() != group_id]
    raw_config["basic_feature_groups"] = kept
    return len(kept) != len(rows)


def to_runtime(group: dict):
    group = deepcopy(group)
    return SimpleNamespace(
        group_id=group["group_id"],
        currency=SimpleNamespace(**group["currency"]),
        signin=SimpleNamespace(**group["signin"]),
        chat_reward=SimpleNamespace(**group["chat_reward"]),
    )

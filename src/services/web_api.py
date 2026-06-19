"""FinCenter 插件页面后端 API。"""
from __future__ import annotations

import base64
import inspect
import os
import re
import uuid
from pathlib import Path

from quart import jsonify, request

from src.core.database import (
    GoodsDefinition,
    GoodsMarketPrice,
    MarketGroupBinding,
    PaidCommand,
    StockCompany,
    StockEventState,
    StockHistory,
    StockHolding,
    StockNews,
    UserAccount,
    UserBackpack,
    get_china_time,
)
from src.markets.stock import StockTechnicalState
from src.services import basic_features
from src.services.command_registry import list_other_plugin_commands


class FinCenterWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register(self):
        names = {self.plugin.name, "FinCenter", "astrbot_plugin_fincenter"}
        for name in names:
            admin = f"/{name}/admin"
            routes = [
                ("/overview", self.get_overview, ["GET"], "FinCenter 总览"),
                ("/options", self.get_options, ["GET"], "读取 FinCenter 可选项"),
                ("/discover-groups", self.discover_groups, ["GET"], "发现机器人所在群"),
                ("/groups/discover", self.discover_groups, ["GET"], "发现机器人所在群"),
                ("/settings", self.get_settings, ["GET"], "读取 FinCenter 设置"),
                ("/settings", self.save_settings, ["POST"], "保存 FinCenter 设置"),
                ("/binding", self.set_binding, ["POST"], "设置模块分组绑定"),
                ("/binding/remove", self.remove_binding, ["POST"], "删除模块分组绑定"),
                ("/module", self.set_module, ["POST"], "启停模块"),
                ("/group/remove", self.remove_group, ["POST"], "删除模块组"),
                ("/basic/config", self.get_basic_config, ["GET"], "读取基础功能组"),
                ("/basic/config", self.save_basic_config, ["POST"], "保存基础功能组"),
                ("/goods/config", self.get_goods_config, ["GET"], "读取物资组配置"),
                ("/goods/item", self.save_goods_item, ["POST"], "保存物资"),
                ("/goods/item/remove", self.remove_goods_item, ["POST"], "删除物资"),
                ("/goods/item/price", self.set_goods_price, ["POST"], "设置物资价格"),
                ("/goods/reset", self.reset_goods_prices, ["POST"], "重置物资价格"),
                ("/stock/config", self.get_stock_config, ["GET"], "读取股市组配置"),
                ("/stock/company", self.save_stock_company, ["POST"], "保存股票"),
                ("/stock/company/remove", self.remove_stock_company, ["POST"], "删除股票"),
                ("/stock/open-state", self.set_stock_open_state, ["POST"], "设置开休市"),
                ("/paid/config", self.get_paid_config, ["GET"], "读取付费组配置"),
                ("/paid/binding", self.set_paid_binding, ["POST"], "设置付费组绑定"),
                ("/paid/command", self.save_paid_command, ["POST"], "保存付费命令"),
                ("/paid/command/remove", self.remove_paid_command, ["POST"], "删除付费命令"),
                ("/paid/command/toggle", self.toggle_paid_command, ["POST"], "启停付费命令"),
                ("/paid/scan", self.scan_commands, ["GET"], "扫描插件命令"),
            ]
            for path, handler, methods, desc in routes:
                self.plugin.context.register_web_api(f"{admin}{path}", handler, methods, desc)

            # 兼容旧页面调用的 paid/* 路由。
            legacy = f"/{name}/paid"
            self.plugin.context.register_web_api(f"{legacy}/config", self.get_paid_config, ["GET"], "FinCenter 付费配置")
            self.plugin.context.register_web_api(f"{legacy}/binding", self.set_paid_binding, ["POST"], "设置付费组绑定")
            self.plugin.context.register_web_api(f"{legacy}/command", self.save_paid_command, ["POST"], "保存付费命令")
            self.plugin.context.register_web_api(f"{legacy}/command/remove", self.remove_paid_command, ["POST"], "删除付费命令")
            self.plugin.context.register_web_api(f"{legacy}/command/toggle", self.toggle_paid_command, ["POST"], "启停付费命令")
            self.plugin.context.register_web_api(f"{legacy}/scan", self.scan_commands, ["GET"], "扫描插件命令")

    # ---- 通用工具 ----
    @staticmethod
    def _ok(data=None, message: str = ""):
        return jsonify({"status": "ok", "data": data if data is not None else {}, "message": message})

    @staticmethod
    def _err(message: str):
        return jsonify({"status": "error", "message": message})

    @staticmethod
    async def _body() -> dict:
        return await request.get_json(force=True, silent=True) or {}

    @staticmethod
    def _to_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
        return bool(value)

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_id(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _module_getter_name(module: str) -> str:
        return {
            "basic": "get_basic_binding",
            "stock": "get_stock_binding",
            "goods": "get_goods_binding",
            "paid": "get_paid_binding",
        }.get(module, "")

    def _get_binding(self, physical_group_id: str, module: str) -> tuple[bool, str]:
        getter_name = self._module_getter_name(module)
        getter = getattr(self.plugin, getter_name, None)
        if not getter:
            return True, physical_group_id
        return getter(physical_group_id)

    @staticmethod
    def _sorted_values(values) -> list[str]:
        cleaned = {
            str(v).strip()
            for v in values
            if FinCenterWebApi._is_real_option_value(v)
        }
        return sorted(cleaned, key=lambda x: (x.startswith("__"), x.lower()))

    @staticmethod
    def _is_real_option_value(value) -> bool:
        value = str(value or "").strip()
        if not value:
            return False
        lowered = value.lower()
        blocked = {
            "__global__",
            "__pending__",
            "示例群号",
            "示例",
            "sample",
            "example",
        }
        if value in blocked or lowered in blocked:
            return False
        temp_prefixes = (
            "group_",
            "goods_group_",
            "stock_group_",
            "paid_group_",
            "goods_",
            "stock_",
            "command_",
        )
        return not any(lowered.startswith(prefix) and lowered[len(prefix):].isdigit() for prefix in temp_prefixes)

    def _set_raw_config_value(self, section: str, key: str, value):
        data = self.plugin._raw_config.setdefault(section, {})
        if isinstance(data, dict):
            data[key] = value

    def _persist_raw_config(self):
        save_config = getattr(self.plugin._raw_config, "save_config", None)
        if callable(save_config):
            save_config()

    async def _maybe_call(self, obj, *args, **kwargs):
        if not callable(obj):
            return None
        try:
            result = obj(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception:
            return None

    def _collect_group_rows(self, payload, source: str) -> list[dict]:
        rows = []
        if isinstance(payload, dict):
            if "data" in payload:
                return self._collect_group_rows(payload.get("data"), source)
            payload = [payload]
        if not isinstance(payload, (list, tuple, set)):
            return rows
        for item in payload:
            if not isinstance(item, dict):
                continue
            group_id = (
                item.get("group_id")
                or item.get("group")
                or item.get("id")
                or item.get("groupId")
                or item.get("room_id")
            )
            group_id = self._clean_id(group_id)
            if not self._is_real_option_value(group_id):
                continue
            name = (
                item.get("group_name")
                or item.get("groupName")
                or item.get("name")
                or item.get("nickname")
                or item.get("room_name")
                or ""
            )
            rows.append({"group_id": group_id, "name": str(name or ""), "source": source})
        return rows

    def _context_candidates(self) -> list:
        seen = set()
        queue = [getattr(self.plugin, "context", None)]
        out = []
        attr_names = (
            "platform_manager", "provider_manager", "platforms", "providers",
            "platform_insts", "provider_insts", "instances", "bots", "clients",
            "bot", "client", "adapter", "api",
        )
        while queue and len(out) < 80:
            obj = queue.pop(0)
            if obj is None or id(obj) in seen:
                continue
            seen.add(id(obj))
            out.append(obj)
            for name in attr_names:
                try:
                    value = getattr(obj, name)
                except Exception:
                    continue
                if isinstance(value, dict):
                    queue.extend(value.values())
                elif isinstance(value, (list, tuple, set)):
                    queue.extend(value)
                elif value is not None and not isinstance(value, (str, bytes, int, float, bool)):
                    queue.append(value)
        return out

    async def _discover_context_groups(self) -> list[dict]:
        rows = []
        for obj in self._context_candidates():
            source = obj.__class__.__name__
            for method_name in ("get_group_list", "get_groups", "group_list", "get_joined_groups"):
                result = await self._maybe_call(getattr(obj, method_name, None))
                rows.extend(self._collect_group_rows(result, source))
            call_action = getattr(obj, "call_action", None)
            if callable(call_action):
                for action in ("get_group_list", "get_group_info"):
                    result = await self._maybe_call(call_action, action)
                    rows.extend(self._collect_group_rows(result, source))
            api = getattr(obj, "api", None)
            call_action = getattr(api, "call_action", None) if api is not None else None
            if callable(call_action):
                result = await self._maybe_call(call_action, "get_group_list")
                rows.extend(self._collect_group_rows(result, source))
        dedup = {}
        for row in rows:
            dedup.setdefault(row["group_id"], row)
        return sorted(dedup.values(), key=lambda x: x["group_id"])

    # ---- 总览 / 设置 ----
    async def get_overview(self):
        physical_group_id = self._clean_id(request.args.get("group_id", ""))
        bindings = {}
        if physical_group_id:
            for module in ("basic", "stock", "goods", "paid"):
                enabled, group_id = self._get_binding(physical_group_id, module)
                bindings[module] = {"enabled": enabled, "group_id": group_id}
        return self._ok({
            "group_id": physical_group_id,
            "bindings": bindings,
            "modules": {
                "stock": bool(self.plugin.stock_market),
                "goods": bool(self.plugin.goods_market),
                "paid": bool(self.plugin.config.paid_cmd.paid_cmd_enabled),
            },
            "currency": {
                "name": self.plugin.config.currency.currency_name,
                "icon": self.plugin.config.currency.currency_icon,
            },
        })

    async def get_options(self):
        goods_group_id = self._clean_id(request.args.get("goods_group_id", ""))
        stock_group_id = self._clean_id(request.args.get("stock_group_id", ""))
        paid_group_id = self._clean_id(request.args.get("paid_group_id", ""))

        physical_groups = set()
        basic_groups = {basic_features.DEFAULT_GROUP_ID}
        stock_groups = set()
        goods_groups = set()
        paid_groups = {self.plugin.paid_command_service.GLOBAL_GROUP}
        goods_ids = set()
        stock_codes = set()
        paid_commands = set()

        with self.plugin.db.session_scope() as session:
            for row in session.query(MarketGroupBinding).all():
                physical_groups.add(row.physical_group_id)
                if row.module == "basic":
                    basic_groups.add(row.market_group_id)
                elif row.module == "stock":
                    stock_groups.add(row.market_group_id)
                elif row.module == "goods":
                    goods_groups.add(row.market_group_id)
                elif row.module == "paid":
                    paid_groups.add(row.market_group_id)

            for row in session.query(UserAccount.group_id).distinct().all():
                physical_groups.add(row[0])

            for row in session.query(StockCompany.group_id).distinct().all():
                stock_groups.add(row[0])
            for row in session.query(GoodsDefinition.group_id).distinct().all():
                goods_groups.add(row[0])
            for row in session.query(PaidCommand.group_id).distinct().all():
                paid_groups.add(row[0])

            if goods_group_id:
                for row in session.query(GoodsDefinition.goods_id).filter_by(group_id=goods_group_id).distinct().all():
                    goods_ids.add(row[0])
            if stock_group_id:
                for row in session.query(StockCompany.code).filter_by(group_id=stock_group_id).distinct().all():
                    stock_codes.add(row[0])
            if paid_group_id:
                for row in session.query(PaidCommand.command).filter_by(group_id=paid_group_id).distinct().all():
                    paid_commands.add(row[0])

        for group in getattr(self.plugin.config.paid_cmd, "paid_cmd_groups", []) or []:
            group_id = self._clean_id(group.get("group_id"))
            if group_id:
                paid_groups.add(group_id)
                if paid_group_id and group_id == paid_group_id:
                    for cmd in group.get("commands", []) or []:
                        paid_commands.add(cmd.get("command", ""))

        for item in getattr(self.plugin.config.paid_cmd, "paid_cmd_group_bindings", []) or []:
            physical_groups.add(item.get("group_id", ""))
            paid_groups.add(item.get("paid_group_id", ""))

        for group in basic_features.list_groups(self.plugin._raw_config, self.plugin.config):
            basic_groups.add(group.get("group_id", ""))

        for comp in getattr(self.plugin.config.stock, "stock_companies", []) or []:
            if stock_group_id:
                stock_codes.add(comp.get("code", ""))

        return self._ok({
            "physical_groups": self._sorted_values(v for v in physical_groups if v not in ("__global__", "__pending__")),
            "basic_groups": self._sorted_values(basic_groups),
            "stock_groups": self._sorted_values(stock_groups),
            "goods_groups": self._sorted_values(goods_groups),
            "paid_groups": self._sorted_values(paid_groups),
            "goods_ids": self._sorted_values(goods_ids),
            "stock_codes": self._sorted_values(stock_codes),
            "paid_commands": self._sorted_values(paid_commands),
            "scanned_commands": list_other_plugin_commands(),
        })

    async def discover_groups(self):
        rows = {row["group_id"]: row for row in await self._discover_context_groups()}
        with self.plugin.db.session_scope() as session:
            for row in session.query(MarketGroupBinding.physical_group_id).distinct().all():
                group_id = self._clean_id(row[0])
                if self._is_real_option_value(group_id):
                    rows.setdefault(group_id, {"group_id": group_id, "name": "", "source": "FinCenter绑定"})
            for row in session.query(UserAccount.group_id).distinct().all():
                group_id = self._clean_id(row[0])
                if self._is_real_option_value(group_id):
                    rows.setdefault(group_id, {"group_id": group_id, "name": "", "source": "账户数据"})
        return self._ok(sorted(rows.values(), key=lambda x: x["group_id"]))

    async def get_settings(self):
        cfg = self.plugin.config
        return self._ok({
            "basic": {
                "admin_ids": cfg.basic.admin_ids,
                "cross_group_data": cfg.basic.cross_group_data,
                "group_filter_enabled": cfg.basic.group_filter_enabled,
                "group_whitelist": cfg.basic.group_whitelist,
                "group_blacklist": cfg.basic.group_blacklist,
            },
            "currency": cfg.currency.__dict__,
            "signin": cfg.signin.__dict__,
            "chat_reward": cfg.chat_reward.__dict__,
            "stock": {
                "stock_enabled": cfg.stock.stock_enabled,
                "stock_volatility": cfg.stock.stock_volatility,
                "stock_update_interval": cfg.stock.stock_update_interval,
                "stock_fee_rate": cfg.stock.stock_fee_rate,
                "stock_trading_hours": cfg.stock.stock_trading_hours,
                "stock_trend_enabled": cfg.stock.stock_trend_enabled,
                "stock_tech_analysis_enabled": cfg.stock.stock_tech_analysis_enabled,
                "stock_kline_candles": cfg.stock.stock_kline_candles,
                "stock_font": cfg.stock.stock_font,
            },
            "stock_news": cfg.stock_news.__dict__,
            "goods": cfg.goods.__dict__,
            "paid_cmd": {
                "paid_cmd_enabled": cfg.paid_cmd.paid_cmd_enabled,
                "paid_cmd_default_cost": cfg.paid_cmd.paid_cmd_default_cost,
                "paid_cmd_insufficient_msg": cfg.paid_cmd.paid_cmd_insufficient_msg,
                "paid_cmd_deduct_msg": cfg.paid_cmd.paid_cmd_deduct_msg,
                "paid_cmd_ignore_admin": cfg.paid_cmd.paid_cmd_ignore_admin,
                "paid_cmd_prefixes": cfg.paid_cmd.paid_cmd_prefixes,
            },
            "rendering": cfg.rendering.__dict__,
        })

    async def save_settings(self):
        body = await self._body()
        cfg = self.plugin.config

        self._apply_basic_settings(body.get("basic", {}))
        self._apply_object_settings("currency", cfg.currency, body.get("currency", {}), {
            "currency_name": str,
            "currency_icon": str,
            "initial_balance": float,
            "open_account_cost": float,
        })
        self._apply_object_settings("signin", cfg.signin, body.get("signin", {}), {
            "signin_enabled": bool,
            "signin_reward_base": float,
            "signin_reward_var": float,
            "signin_consecutive_bonus": float,
            "signin_max_consecutive": int,
        })
        self._apply_object_settings("chat_reward", cfg.chat_reward, body.get("chat_reward", {}), {
            "chat_reward_enabled": bool,
            "chat_reward_amount": float,
            "chat_reward_cooldown": int,
            "chat_reward_daily_limit": int,
        })
        self._apply_object_settings("stock", cfg.stock, body.get("stock", {}), {
            "stock_volatility": float,
            "stock_update_interval": int,
            "stock_fee_rate": float,
            "stock_trading_hours": bool,
            "stock_trend_enabled": bool,
            "stock_tech_analysis_enabled": bool,
            "stock_kline_candles": int,
            "stock_font": str,
        })
        self._apply_object_settings("stock_news", cfg.stock_news, body.get("stock_news", {}), {
            "stock_news_enabled": bool,
            "stock_news_source": str,
            "stock_news_trigger_prob": float,
            "stock_news_broadcast": bool,
            "stock_news_history_count": int,
            "stock_news_provider_id": str,
            "stock_llm_prompt_template": str,
            "stock_news_prob_major_positive": float,
            "stock_news_prob_positive": float,
            "stock_news_prob_slight_positive": float,
            "stock_news_prob_neutral": float,
            "stock_news_prob_slight_negative": float,
            "stock_news_prob_negative": float,
            "stock_news_prob_major_negative": float,
            "stock_news_prob_volatility": float,
        })
        self._apply_object_settings("goods", cfg.goods, body.get("goods", {}), {
            "goods_refresh_interval": int,
            "goods_price_volatility": float,
            "goods_user_trade_enabled": bool,
            "goods_user_trade_tax": float,
        })
        self._apply_object_settings("paid_cmd", cfg.paid_cmd, body.get("paid_cmd", {}), {
            "paid_cmd_enabled": bool,
            "paid_cmd_default_cost": float,
            "paid_cmd_insufficient_msg": str,
            "paid_cmd_deduct_msg": str,
            "paid_cmd_ignore_admin": bool,
        })
        paid_cmd = body.get("paid_cmd", {}) or {}
        if "paid_cmd_prefixes" in paid_cmd:
            prefixes = paid_cmd.get("paid_cmd_prefixes")
            if isinstance(prefixes, str):
                prefixes = [p.strip() for p in re.split(r"[\n,，]+", prefixes) if p.strip()]
            if isinstance(prefixes, list):
                cfg.paid_cmd.paid_cmd_prefixes = [str(p) for p in prefixes]
                self._set_raw_config_value("paid_cmd", "paid_cmd_prefixes", cfg.paid_cmd.paid_cmd_prefixes)
        self._apply_object_settings("rendering", cfg.rendering, body.get("rendering", {}), {
            "render_strategy": str,
        })

        self._refresh_runtime_settings()
        self._persist_raw_config()
        return self._ok(message="设置已应用到当前插件实例")

    def _apply_basic_settings(self, data: dict):
        if not isinstance(data, dict):
            return
        cfg = self.plugin.config.basic
        list_fields = {"admin_ids", "group_whitelist", "group_blacklist"}
        bool_fields = {"cross_group_data", "group_filter_enabled"}
        for key in list_fields:
            if key in data:
                value = data.get(key)
                if isinstance(value, str):
                    value = [x.strip() for x in re.split(r"[\n,，\s]+", value) if x.strip()]
                if isinstance(value, list):
                    setattr(cfg, key, [str(x).strip() for x in value if str(x).strip()])
                    self._set_raw_config_value("basic", key, getattr(cfg, key))
        for key in bool_fields:
            if key in data:
                value = self._to_bool(data.get(key), getattr(cfg, key))
                setattr(cfg, key, value)
                self._set_raw_config_value("basic", key, value)

    def _apply_object_settings(self, section: str, obj, data: dict, fields: dict):
        if not isinstance(data, dict):
            return
        for key, caster in fields.items():
            if key not in data:
                continue
            old = getattr(obj, key)
            raw = data.get(key)
            try:
                if caster is bool:
                    value = self._to_bool(raw, old)
                elif caster is int:
                    value = self._to_int(raw, old)
                elif caster is float:
                    value = self._to_float(raw, old)
                else:
                    value = str(raw)
            except Exception:
                value = old
            setattr(obj, key, value)
            self._set_raw_config_value(section, key, value)

    def _refresh_runtime_settings(self):
        if self.plugin.stock_market:
            stock = self.plugin.stock_market
            cfg = self.plugin.config.stock
            news = self.plugin.config.stock_news
            stock.volatility = cfg.stock_volatility
            stock.update_interval = cfg.stock_update_interval
            stock.fee_rate = cfg.stock_fee_rate
            stock.trading_hours = cfg.stock_trading_hours
            stock.trend_enabled = cfg.stock_trend_enabled
            stock.tech_enabled = cfg.stock_tech_analysis_enabled
            stock.news_enabled = news.stock_news_enabled
            stock.news_trigger_prob = news.stock_news_trigger_prob
            stock.news_history_count = news.stock_news_history_count
            stock.news_broadcast = news.stock_news_broadcast
        if self.plugin.goods_market:
            goods = self.plugin.goods_market
            cfg = self.plugin.config.goods
            goods.refresh_interval = cfg.goods_refresh_interval
            goods.price_volatility = cfg.goods_price_volatility
            goods.user_trade_enabled = cfg.goods_user_trade_enabled
            goods.trade_tax = cfg.goods_user_trade_tax

    # ---- 模块 / 群绑定 ----
    async def set_binding(self):
        body = await self._body()
        module = self._clean_id(body.get("module"))
        if module not in ("basic", "stock", "goods", "paid"):
            return self._err("module 必须是 basic/stock/goods/paid")
        physical_group_id = self._clean_id(body.get("physical_group_id"))
        market_group_id = self._clean_id(body.get("market_group_id") or body.get("group_id") or physical_group_id)
        enabled = self._to_bool(body.get("enabled", True), True)
        if not physical_group_id:
            return self._err("physical_group_id 不能为空")
        self.plugin.set_market_binding(physical_group_id, module, market_group_id, enabled)
        return self._ok({"module": module, "enabled": enabled, "group_id": market_group_id})

    async def remove_binding(self):
        body = await self._body()
        physical_group_id = self._clean_id(body.get("physical_group_id"))
        module = self._clean_id(body.get("module"))
        if module not in ("basic", "stock", "goods", "paid", "all"):
            return self._err("module 必须是 basic/stock/goods/paid/all")
        if not physical_group_id:
            return self._err("physical_group_id 不能为空")
        with self.plugin.db.session_scope() as session:
            query = session.query(MarketGroupBinding).filter_by(physical_group_id=physical_group_id)
            if module != "all":
                query = query.filter_by(module=module)
            count = query.delete()
        return self._ok({"count": count})

    async def set_module(self):
        body = await self._body()
        module = self._clean_id(body.get("module"))
        enabled = self._to_bool(body.get("enabled", True), True)
        if module == "stock":
            result = self.plugin.enable_stock_market() if enabled else self.plugin.disable_stock_market()
        elif module == "goods":
            result = self.plugin.enable_goods_market() if enabled else self.plugin.disable_goods_market()
        elif module == "paid":
            self.plugin.config.paid_cmd.paid_cmd_enabled = enabled
            self._set_raw_config_value("paid_cmd", "paid_cmd_enabled", enabled)
            result = True, "付费指令拦截已启用" if enabled else "付费指令拦截已禁用"
        else:
            return self._err("module 必须是 stock/goods/paid")
        self._persist_raw_config()
        return self._ok({"changed": bool(result[0]), "enabled": enabled}, result[1])

    async def remove_group(self):
        body = await self._body()
        module = self._clean_id(body.get("module"))
        group_id = self._clean_id(body.get("group_id"))
        if module not in ("basic", "stock", "goods", "paid"):
            return self._err("module 必须是 basic/stock/goods/paid")
        if not group_id:
            return self._err("group_id 不能为空")
        if group_id == self.plugin.paid_command_service.GLOBAL_GROUP:
            return self._err("全局付费组不能删除")
        if module == "basic" and group_id == basic_features.DEFAULT_GROUP_ID:
            return self._err("默认基础功能组不能删除")

        if module == "basic":
            count = self._remove_basic_group(group_id)
        elif module == "goods":
            count = self._remove_goods_group(group_id)
        elif module == "stock":
            count = self._remove_stock_group(group_id)
        else:
            count = self._remove_paid_group(group_id)
        return self._ok({"count": count})

    def _remove_basic_group(self, group_id: str) -> int:
        removed = basic_features.remove_group(self.plugin._raw_config, group_id)
        with self.plugin.db.session_scope() as session:
            count = session.query(MarketGroupBinding).filter_by(module="basic", market_group_id=group_id).delete()
        self._persist_raw_config()
        return max(count, 1 if removed else 0)

    # ---- 基础功能组 ----
    async def get_basic_config(self):
        group_id = self._clean_id(request.args.get("basic_group_id", "")) or basic_features.DEFAULT_GROUP_ID
        group = basic_features.get_group(self.plugin._raw_config, self.plugin.config, group_id)
        return self._ok({
            "basic_group_id": group["group_id"],
            "group": group,
            "groups": basic_features.list_groups(self.plugin._raw_config, self.plugin.config),
        })

    async def save_basic_config(self):
        body = await self._body()
        group_id = self._clean_id(body.get("basic_group_id") or body.get("group_id"))
        if not group_id:
            return self._err("basic_group_id 不能为空")
        payload = dict(body.get("group") or {})
        payload["group_id"] = group_id
        group = basic_features.upsert_group(self.plugin._raw_config, self.plugin.config, payload)
        self._persist_raw_config()
        return self._ok({"basic_group_id": group["group_id"], "group": group})

    def _remove_goods_group(self, group_id: str) -> int:
        with self.plugin.db.session_scope() as session:
            goods_ids = [
                row[0] for row in session.query(GoodsDefinition.goods_id).filter_by(group_id=group_id).all()
            ]
        if self.plugin.goods_market:
            count = 0
            for goods_id in goods_ids:
                if self.plugin.goods_market.remove_goods(group_id, goods_id):
                    count += 1
            with self.plugin.db.session_scope() as session:
                session.query(MarketGroupBinding).filter_by(module="goods", market_group_id=group_id).delete()
            return count

        with self.plugin.db.session_scope() as session:
            definitions = session.query(GoodsDefinition).filter_by(group_id=group_id).all()
            image_paths = [d.preview_image for d in definitions if d.preview_image]
            count = len(definitions)
            markets = {
                m.goods_id: float(m.current_price or 0)
                for m in session.query(GoodsMarketPrice).filter_by(group_id=group_id).all()
            }
            backpacks = session.query(UserBackpack).filter_by(group_id=group_id).all()
            for bp in backpacks:
                refund = float(bp.amount or 0) * markets.get(bp.goods_id, 0.0)
                if refund > 0:
                    user = session.query(UserAccount).filter_by(
                        group_id=group_id, user_id=bp.user_id
                    ).first()
                    if user:
                        user.add_balance(refund)
            session.query(GoodsMarketPrice).filter_by(group_id=group_id).delete()
            session.query(UserBackpack).filter_by(group_id=group_id).delete()
            session.query(GoodsDefinition).filter_by(group_id=group_id).delete()
            session.query(MarketGroupBinding).filter_by(module="goods", market_group_id=group_id).delete()
        for path in image_paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        return count

    def _remove_stock_group(self, group_id: str) -> int:
        with self.plugin.db.session_scope() as session:
            count = session.query(StockCompany).filter_by(group_id=group_id).count()
            session.query(StockHolding).filter_by(group_id=group_id).delete()
            session.query(StockHistory).filter_by(group_id=group_id).delete()
            session.query(StockNews).filter_by(group_id=group_id).delete()
            session.query(StockEventState).filter_by(group_id=group_id).delete()
            session.query(StockCompany).filter_by(group_id=group_id).delete()
            session.query(MarketGroupBinding).filter_by(module="stock", market_group_id=group_id).delete()
        if self.plugin.stock_market:
            market = self.plugin.stock_market
            with market.lock:
                for store in (market.prices, market.trend_levels, market.trend_duration, market.base_prices, market.current_candles, market.tech_states):
                    store.pop(group_id, None)
            with market._snapshot_lock:
                market._price_snapshot.pop(group_id, None)
        return count

    def _remove_paid_group(self, group_id: str) -> int:
        with self.plugin.db.session_scope() as session:
            count = session.query(PaidCommand).filter_by(group_id=group_id).delete()
            session.query(MarketGroupBinding).filter_by(module="paid", market_group_id=group_id).delete()
        return count

    # ---- 物资组 ----
    async def get_goods_config(self):
        physical_group_id = self._clean_id(request.args.get("group_id", ""))
        goods_group_id = self._clean_id(request.args.get("goods_group_id", ""))
        enabled, bound_group = self.plugin.get_goods_binding(physical_group_id) if physical_group_id else (True, goods_group_id)
        group_id = goods_group_id or bound_group or physical_group_id
        return self._ok({
            "physical_group_id": physical_group_id,
            "enabled": enabled,
            "goods_group_id": group_id,
            "items": self._list_goods(group_id) if group_id else [],
            "options": (await self._options_payload(goods_group_id=group_id)),
        })

    async def _options_payload(self, goods_group_id="", stock_group_id="", paid_group_id=""):
        # 内部复用轻量查询，避免前端每个模块都必须再请求 options。
        old_args = request.args
        _ = old_args
        goods_ids = set()
        stock_codes = set()
        paid_commands = set()
        with self.plugin.db.session_scope() as session:
            if goods_group_id:
                for row in session.query(GoodsDefinition.goods_id).filter_by(group_id=goods_group_id).distinct().all():
                    goods_ids.add(row[0])
            if stock_group_id:
                for row in session.query(StockCompany.code).filter_by(group_id=stock_group_id).distinct().all():
                    stock_codes.add(row[0])
            if paid_group_id:
                for row in session.query(PaidCommand.command).filter_by(group_id=paid_group_id).distinct().all():
                    paid_commands.add(row[0])
        return {
            "goods_ids": self._sorted_values(goods_ids),
            "stock_codes": self._sorted_values(stock_codes),
            "paid_commands": self._sorted_values(paid_commands),
        }

    def _list_goods(self, group_id: str) -> list[dict]:
        with self.plugin.db.session_scope() as session:
            definitions = session.query(GoodsDefinition).filter_by(group_id=group_id).order_by(GoodsDefinition.goods_id).all()
            rows = []
            for d in definitions:
                market = session.query(GoodsMarketPrice).filter_by(group_id=group_id, goods_id=d.goods_id).first()
                rows.append({
                    "group_id": d.group_id,
                    "goods_id": d.goods_id,
                    "name": d.name,
                    "icon": d.icon,
                    "preview_image": d.preview_image or "",
                    "base_price": float(d.base_price or 0),
                    "min_price": float(d.min_price or 0),
                    "max_price": float(d.max_price or 0),
                    "volatility": float(d.volatility or 0),
                    "current_price": float(market.current_price if market else d.base_price or 0),
                    "previous_price": float(market.previous_price if market else d.base_price or 0),
                })
        return rows

    async def save_goods_item(self):
        body = await self._body()
        group_id = self._clean_id(body.get("goods_group_id") or body.get("group_id"))
        goods_id = self._clean_id(body.get("goods_id"))
        name = self._clean_id(body.get("name"))
        if not group_id or not name:
            return self._err("goods_group_id 和 name 不能为空")
        if not goods_id:
            goods_id = self._new_goods_id(group_id)
        base_price = self._to_float(body.get("base_price"), 10.0)
        min_price = self._to_float(body.get("min_price"), base_price * 0.1)
        max_price = self._to_float(body.get("max_price"), base_price * 10.0)
        volatility = self._to_float(body.get("volatility"), self.plugin.config.goods.goods_price_volatility)
        current_price = self._to_float(body.get("current_price"), base_price)
        icon = str(body.get("icon") or "📦")
        preview_image = self._save_goods_image(group_id, goods_id, body)

        with self.plugin.db.session_scope() as session:
            definition = session.query(GoodsDefinition).filter_by(group_id=group_id, goods_id=goods_id).first()
            if not definition:
                definition = GoodsDefinition(group_id=group_id, goods_id=goods_id, created_at=get_china_time())
                session.add(definition)
            definition.name = name
            definition.icon = icon
            definition.base_price = max(0.01, base_price)
            definition.min_price = max(0.0, min_price)
            definition.max_price = max(definition.min_price + 0.01, max_price)
            definition.volatility = max(0.0, volatility)
            if preview_image:
                definition.preview_image = preview_image

            market = session.query(GoodsMarketPrice).filter_by(group_id=group_id, goods_id=goods_id).first()
            if not market:
                market = GoodsMarketPrice(group_id=group_id, goods_id=goods_id, previous_price=current_price)
                session.add(market)
            market.current_price = max(0.01, current_price)
            if not market.previous_price:
                market.previous_price = market.current_price
            market.last_refresh = get_china_time()

        return self._ok({"goods_group_id": group_id, "goods_id": goods_id})

    def _new_goods_id(self, group_id: str) -> str:
        with self.plugin.db.session_scope() as session:
            for _ in range(12):
                goods_id = f"goods_{uuid.uuid4().hex[:8]}"
                exists = session.query(GoodsDefinition).filter_by(
                    group_id=group_id,
                    goods_id=goods_id,
                ).first()
                if not exists:
                    return goods_id
        return f"goods_{uuid.uuid4().hex}"

    def _save_goods_image(self, group_id: str, goods_id: str, body: dict) -> str:
        image_data = body.get("image_data")
        if not image_data:
            return ""
        filename = str(body.get("image_name") or "")
        match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", str(image_data), re.S)
        mime = ""
        payload = str(image_data)
        if match:
            mime = match.group(1).lower()
            payload = match.group(2)
        ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
        ext = ext_map.get(mime) or os.path.splitext(filename)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            ext = ".png"
        safe_group = re.sub(r"[^A-Za-z0-9_.-]+", "_", group_id)
        safe_goods = re.sub(r"[^A-Za-z0-9_.-]+", "_", goods_id)
        out_dir = Path(self.plugin.data_dir) / "assets" / "goods"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_group}_{safe_goods}_{uuid.uuid4().hex[:8]}{ext}"
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(payload))
        return str(out_path)

    async def remove_goods_item(self):
        body = await self._body()
        group_id = self._clean_id(body.get("goods_group_id") or body.get("group_id"))
        goods_id = self._clean_id(body.get("goods_id"))
        if not group_id or not goods_id:
            return self._err("goods_group_id 和 goods_id 不能为空")
        if self.plugin.goods_market:
            ok = self.plugin.goods_market.remove_goods(group_id, goods_id)
        else:
            ok = self._remove_goods_without_engine(group_id, goods_id)
        return self._ok({"ok": ok}) if ok else self._err("物资不存在")

    def _remove_goods_without_engine(self, group_id: str, goods_id: str) -> bool:
        with self.plugin.db.session_scope() as session:
            definition = session.query(GoodsDefinition).filter_by(group_id=group_id, goods_id=goods_id).first()
            if not definition:
                return False
            preview_image = definition.preview_image
            session.query(GoodsMarketPrice).filter_by(group_id=group_id, goods_id=goods_id).delete()
            session.query(UserBackpack).filter_by(group_id=group_id, goods_id=goods_id).delete()
            session.delete(definition)
        if preview_image and os.path.exists(preview_image):
            try:
                os.remove(preview_image)
            except Exception:
                pass
        return True

    async def set_goods_price(self):
        body = await self._body()
        group_id = self._clean_id(body.get("goods_group_id") or body.get("group_id"))
        goods_id = self._clean_id(body.get("goods_id"))
        price = self._to_float(body.get("price"), -1)
        if price <= 0:
            return self._err("price 必须大于 0")
        ok = False
        with self.plugin.db.session_scope() as session:
            market = session.query(GoodsMarketPrice).filter_by(group_id=group_id, goods_id=goods_id).first()
            if market:
                market.previous_price = market.current_price
                market.current_price = price
                market.last_refresh = get_china_time()
                ok = True
        return self._ok({"ok": ok}) if ok else self._err("物资不存在")

    async def reset_goods_prices(self):
        body = await self._body()
        group_id = self._clean_id(body.get("goods_group_id") or body.get("group_id"))
        if not group_id:
            return self._err("goods_group_id 不能为空")
        count = 0
        with self.plugin.db.session_scope() as session:
            definitions = session.query(GoodsDefinition).filter_by(group_id=group_id).all()
            for d in definitions:
                market = session.query(GoodsMarketPrice).filter_by(group_id=group_id, goods_id=d.goods_id).first()
                if market:
                    market.previous_price = d.base_price
                    market.current_price = d.base_price
                    market.last_refresh = get_china_time()
                    count += 1
        return self._ok({"count": count})

    # ---- 股市组 ----
    async def get_stock_config(self):
        physical_group_id = self._clean_id(request.args.get("group_id", ""))
        stock_group_id = self._clean_id(request.args.get("stock_group_id", ""))
        enabled, bound_group = self.plugin.get_stock_binding(physical_group_id) if physical_group_id else (True, stock_group_id)
        group_id = stock_group_id or bound_group or physical_group_id
        if group_id and self.plugin.stock_market:
            self.plugin.stock_market.ensure_group_initialized(group_id)
        return self._ok({
            "physical_group_id": physical_group_id,
            "enabled": enabled,
            "stock_group_id": group_id,
            "is_open": bool(getattr(self.plugin.stock_market, "is_open", False)) if self.plugin.stock_market else False,
            "manual_override": getattr(self.plugin.stock_market, "manual_override", None) if self.plugin.stock_market else None,
            "companies": self._list_stock_companies(group_id) if group_id else [],
            "options": (await self._options_payload(stock_group_id=group_id)),
        })

    def _list_stock_companies(self, group_id: str) -> list[dict]:
        with self.plugin.db.session_scope() as session:
            rows = session.query(StockCompany).filter_by(group_id=group_id).order_by(StockCompany.code).all()
            if not rows and not self.plugin.stock_market:
                return [
                    {
                        "group_id": group_id,
                        "code": str(c.get("code", "")).upper(),
                        "name": c.get("name", ""),
                        "icon": c.get("icon", ""),
                        "description": c.get("description", ""),
                        "current_price": float(c.get("initial_price", 100.0)),
                        "trend_level": 0,
                    }
                    for c in self.plugin.config.stock.stock_companies
                    if c.get("code")
                ]
            return [
                {
                    "group_id": r.group_id,
                    "code": r.code,
                    "name": r.name,
                    "icon": r.icon or "",
                    "description": r.description or "",
                    "current_price": float(r.current_price or 0),
                    "trend_level": int(r.trend_level or 0),
                    "last_update": r.last_update.isoformat(sep=" ") if r.last_update else "",
                }
                for r in rows
            ]

    async def save_stock_company(self):
        body = await self._body()
        group_id = self._clean_id(body.get("stock_group_id") or body.get("group_id"))
        code = self._clean_id(body.get("code")).upper()
        name = self._clean_id(body.get("name")) or code
        if not group_id or not code:
            return self._err("stock_group_id 和 code 不能为空")
        price = max(0.01, self._to_float(body.get("current_price") or body.get("initial_price"), 100.0))
        trend_level = max(-3, min(3, self._to_int(body.get("trend_level"), 0)))
        icon = str(body.get("icon") or "")
        description = str(body.get("description") or "")

        with self.plugin.db.session_scope() as session:
            row = session.query(StockCompany).filter_by(group_id=group_id, code=code).first()
            if not row:
                row = StockCompany(group_id=group_id, code=code, last_update=get_china_time())
                session.add(row)
            row.name = name
            row.icon = icon
            row.description = description
            row.current_price = price
            row.trend_level = trend_level
            row.last_update = get_china_time()

        if self.plugin.stock_market:
            self._sync_stock_company_to_engine(group_id, code, name, price, trend_level)
        return self._ok({"stock_group_id": group_id, "code": code})

    def _sync_stock_company_to_engine(self, group_id: str, code: str, name: str, price: float, trend_level: int):
        market = self.plugin.stock_market
        with market.lock:
            market.prices.setdefault(group_id, {})[code] = price
            market.trend_levels.setdefault(group_id, {})[code] = trend_level
            market.trend_duration.setdefault(group_id, {})[code] = 0
            market.base_prices.setdefault(group_id, {})[code] = price
            market.current_candles.setdefault(group_id, {})[code] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "simulated_volume": 0.0,
                "start_time": get_china_time(),
            }
            market.tech_states.setdefault(group_id, {})[code] = StockTechnicalState()
        with market._snapshot_lock:
            market._price_snapshot.pop(group_id, None)

    async def remove_stock_company(self):
        body = await self._body()
        group_id = self._clean_id(body.get("stock_group_id") or body.get("group_id"))
        code = self._clean_id(body.get("code")).upper()
        if not group_id or not code:
            return self._err("stock_group_id 和 code 不能为空")
        with self.plugin.db.session_scope() as session:
            row = session.query(StockCompany).filter_by(group_id=group_id, code=code).first()
            if not row:
                return self._err("股票不存在")
            session.delete(row)
            session.query(StockHolding).filter_by(group_id=group_id, code=code).delete()
            session.query(StockHistory).filter_by(group_id=group_id, code=code).delete()
            session.query(StockNews).filter_by(group_id=group_id, company_code=code).delete()
            session.query(StockEventState).filter_by(group_id=group_id, company_code=code).delete()
        if self.plugin.stock_market:
            market = self.plugin.stock_market
            with market.lock:
                for store in (market.prices, market.trend_levels, market.trend_duration, market.base_prices, market.current_candles, market.tech_states):
                    store.get(group_id, {}).pop(code, None)
            with market._snapshot_lock:
                market._price_snapshot.pop(group_id, None)
        return self._ok({"code": code})

    async def set_stock_open_state(self):
        body = await self._body()
        mode = self._clean_id(body.get("mode"))
        if not self.plugin.stock_market:
            return self._err("股市模块未启用")
        if mode == "open":
            self.plugin.stock_market.set_open(True)
        elif mode == "close":
            self.plugin.stock_market.set_open(False)
        elif mode == "auto":
            self.plugin.stock_market.manual_override = None
        else:
            return self._err("mode 必须是 open/close/auto")
        return self._ok({"mode": mode})

    # ---- 付费组 ----
    async def get_paid_config(self):
        physical_group_id = self._clean_id(request.args.get("group_id", ""))
        paid_group_id_arg = self._clean_id(request.args.get("paid_group_id", ""))
        enabled, paid_group_id = self.plugin.get_paid_binding(physical_group_id) if physical_group_id else (True, paid_group_id_arg)
        paid_group_id = paid_group_id_arg or paid_group_id
        rows = self.plugin.paid_command_service.list_paid_commands(paid_group_id or None)
        return self._ok({
            "physical_group_id": physical_group_id,
            "paid_enabled": enabled,
            "paid_group_id": paid_group_id,
            "commands": rows,
            "options": (await self._options_payload(paid_group_id=paid_group_id)),
            "currency": {
                "name": self.plugin.config.currency.currency_name,
                "icon": self.plugin.config.currency.currency_icon,
            },
        })

    async def set_paid_binding(self):
        body = await self._body()
        physical_group_id = self._clean_id(body.get("physical_group_id"))
        paid_group_id = self._clean_id(body.get("paid_group_id") or physical_group_id)
        enabled = self._to_bool(body.get("enabled", True), True)
        if not physical_group_id:
            return self._err("physical_group_id 不能为空")
        self.plugin.set_market_binding(physical_group_id, "paid", paid_group_id, enabled)
        return self._ok({"enabled": enabled, "paid_group_id": paid_group_id})

    async def save_paid_command(self):
        body = await self._body()
        paid_group_id = self._clean_id(body.get("paid_group_id"))
        command = self._clean_id(body.get("command"))
        description = self._clean_id(body.get("description"))
        cost = self._to_float(body.get("cost"), self.plugin.config.paid_cmd.paid_cmd_default_cost)
        enabled = self._to_bool(body.get("enabled", True), True)
        if not paid_group_id or not command:
            return self._err("paid_group_id 和 command 不能为空")
        ok = self.plugin.paid_command_service.add_paid_command(paid_group_id, command, cost, description)
        if ok and not enabled:
            self.plugin.paid_command_service.toggle_paid_command(paid_group_id, command, False)
        return self._ok({"ok": ok}) if ok else self._err("保存失败")

    async def remove_paid_command(self):
        body = await self._body()
        paid_group_id = self._clean_id(body.get("paid_group_id"))
        command = self._clean_id(body.get("command"))
        ok = self.plugin.paid_command_service.remove_paid_command(paid_group_id, command)
        return self._ok({"ok": ok}) if ok else self._err("未找到命令")

    async def toggle_paid_command(self):
        body = await self._body()
        paid_group_id = self._clean_id(body.get("paid_group_id"))
        command = self._clean_id(body.get("command"))
        enabled = self._to_bool(body.get("enabled", True), True)
        ok = self.plugin.paid_command_service.toggle_paid_command(paid_group_id, command, enabled)
        return self._ok({"ok": ok}) if ok else self._err("未找到命令")

    async def scan_commands(self):
        return self._ok(list_other_plugin_commands())

"""股市引擎模块

提供股票市场模拟引擎，包含价格更新、趋势计算、技术分析、新闻事件等功能。
所有数据库操作通过 session_scope() 上下文管理器进行，确保事务安全。
交易操作在锁内完成全部数据库写入，消除竞态条件。
"""
import threading
import time
import random
import math
import queue as queue_mod
import asyncio
from datetime import datetime, timedelta

from ..core.database import (
    DB, StockCompany, StockHolding, StockHistory, StockNews,
    UserAccount, get_china_time, sync_network_time
)
from ..services.news import StockNewsGenerator
from ..config import StockConfig, StockNewsConfig


TREND_BASE_RANGES = {
    3: (0.02, 0.05),
    2: (0.01, 0.03),
    1: (0.003, 0.015),
    0: (-0.005, 0.005),
    -1: (-0.015, -0.003),
    -2: (-0.03, -0.01),
    -3: (-0.05, -0.02),
}

TREND_TRANSITIONS = {
    3: {3: 0.50, 2: 0.30, 1: 0.15, 0: 0.05},
    2: {3: 0.20, 2: 0.45, 1: 0.25, 0: 0.10},
    1: {2: 0.15, 1: 0.50, 0: 0.25, -1: 0.10},
    0: {1: 0.20, 0: 0.50, -1: 0.20, 2: 0.05, -2: 0.05},
    -1: {-2: 0.10, -1: 0.50, 0: 0.25, 1: 0.15},
    -2: {-3: 0.10, -2: 0.45, -1: 0.25, 0: 0.20},
    -3: {-3: 0.50, -2: 0.30, -1: 0.15, 0: 0.05},
}

TREND_REVERSION_FACTOR = 0.003
TREND_MAX_DURATION = 15
INTRA_PERIOD_STEPS = 24
VOLUME_BASE_MIN = 80.0
VOLUME_BASE_MAX = 300.0
VOLUME_TREND_MULTIPLIER = 1.8
VOLUME_VOLATILITY_SENSITIVITY = 40.0


class StockTechnicalState:
    """技术分析状态"""
    def __init__(self):
        self.support = None
        self.resistance = None
        self.peak_detected = False
        self.trough_detected = False
        self.recent_highs = []
        self.recent_lows = []
        self.local_maxima = []
        self.local_minima = []
        self.bollinger_upper = None
        self.bollinger_lower = None
        self.bollinger_mid = None


class StockMarket:
    """股市引擎：按 market_group_id 隔离/共享行情。"""

    def __init__(self, db: DB, stock_config: StockConfig, news_config: StockNewsConfig):
        self.db = db
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        self.volatility = stock_config.stock_volatility
        self.update_interval = stock_config.stock_update_interval
        self.fee_rate = stock_config.stock_fee_rate
        self.trading_hours = stock_config.stock_trading_hours
        self.trend_enabled = stock_config.stock_trend_enabled
        self.tech_enabled = stock_config.stock_tech_analysis_enabled

        self.news_enabled = news_config.stock_news_enabled
        self.news_trigger_prob = news_config.stock_news_trigger_prob
        self.news_history_count = news_config.stock_news_history_count
        self.news_broadcast = news_config.stock_news_broadcast
        self.news_generator = StockNewsGenerator(db, news_config) if self.news_enabled else None

        self.companies_config = stock_config.stock_companies
        self.company_params = self._build_company_params(self.companies_config)
        self.is_open = True
        self.manual_override = None

        self._main_loop = None
        self._pending_llm_news = queue_mod.Queue()
        self._price_snapshot = {}
        self._snapshot_lock = threading.Lock()

        self.prices = {}
        self.trend_levels = {}
        self.trend_duration = {}
        self.base_prices = {}
        self.current_candles = {}
        self.tech_states = {}
        self.last_update_time = time.time()
        self.update_count = 0

        sync_network_time()

    def _build_company_params(self, companies_config):
        params = {}
        for comp in companies_config:
            code = comp.get("code", "").upper()
            if not code:
                continue
            params[code] = {
                "volatility": self._safe_float(comp.get("volatility"), self.volatility),
                "liquidity": max(0.1, self._safe_float(comp.get("liquidity"), 1.0)),
                "news_sensitivity": max(0.1, self._safe_float(comp.get("news_sensitivity"), 1.0)),
                "max_change": max(0.01, self._safe_float(comp.get("max_change"), 0.08)),
                "event_max_change": max(0.02, self._safe_float(comp.get("event_max_change"), 0.18)),
            }
        return params

    @staticmethod
    def _safe_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _company_param(self, code, key, default):
        return self.company_params.get(code, {}).get(key, default)

    def _group_dict(self, store, group_id):
        return store.setdefault(str(group_id), {})

    def ensure_group_initialized(self, group_id):
        group_id = str(group_id)
        if group_id in self.prices and self.prices[group_id]:
            return

        with self.lock:
            if group_id in self.prices and self.prices[group_id]:
                return
            prices = self._group_dict(self.prices, group_id)
            trends = self._group_dict(self.trend_levels, group_id)
            durations = self._group_dict(self.trend_duration, group_id)
            bases = self._group_dict(self.base_prices, group_id)
            candles = self._group_dict(self.current_candles, group_id)
            techs = self._group_dict(self.tech_states, group_id)

            with self.db.session_scope() as session:
                now = get_china_time()
                existing_rows = {
                    row.code.upper(): row
                    for row in session.query(StockCompany).filter_by(group_id=group_id).all()
                    if row.code
                }
                config_rows = {}
                for comp_cfg in self.companies_config:
                    code = comp_cfg.get("code", "").upper()
                    if code:
                        config_rows[code] = comp_cfg
                codes = list(config_rows.keys())
                for code in existing_rows:
                    if code not in config_rows:
                        codes.append(code)

                for code in codes:
                    comp_cfg = config_rows.get(code, {})
                    existing = existing_rows.get(code)
                    if existing:
                        price = float(existing.current_price)
                        trend = int(existing.trend_level or 0)
                    else:
                        legacy = session.query(StockCompany).filter_by(
                            group_id="", code=code
                        ).first()
                        price = float(legacy.current_price) if legacy else float(comp_cfg.get("initial_price", 100.0))
                        trend = int(legacy.trend_level) if legacy else 0
                        session.add(StockCompany(
                            group_id=group_id,
                            code=code,
                            name=comp_cfg.get("name", code),
                            icon=comp_cfg.get("icon", ""),
                            description=comp_cfg.get("description", ""),
                            current_price=price,
                            trend_level=trend,
                            last_update=now,
                        ))

                    prices[code] = price
                    trends[code] = trend
                    durations[code] = 0
                    bases[code] = price
                    candles[code] = {
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": 0.0,
                        "simulated_volume": 0.0,
                        "start_time": now,
                    }
                    techs[code] = StockTechnicalState()

                for code in list(prices.keys()):
                    last = session.query(StockHistory).filter_by(
                        group_id=group_id, code=code
                    ).order_by(StockHistory.timestamp.desc()).first()
                    if last:
                        prices[code] = float(last.close)
                        candles[code]["open"] = float(last.close)
                        candles[code]["high"] = float(last.close)
                        candles[code]["low"] = float(last.close)
                        candles[code]["close"] = float(last.close)
                    else:
                        self._seed_initial_history(session, group_id, code)

    def _seed_initial_history(self, session, group_id, code):
        now = get_china_time()
        price = self.prices[group_id][code]
        seed_count = 50
        volatility = self._company_param(code, "volatility", self.volatility)
        liquidity = self._company_param(code, "liquidity", 1.0)
        for i in range(seed_count, 0, -1):
            ts = now - timedelta(seconds=i * max(self.update_interval, 60))
            open_p = price
            seed_change = self._clamp_change(random.gauss(0, volatility * 2), self._company_param(code, "max_change", 0.08))
            high, low, close = self._simulate_intra_period(price, seed_change, volatility)
            pct = abs(close - open_p) / max(open_p, 0.01)
            vol = self._simulate_volume(code, pct, 0, liquidity=liquidity)
            session.add(StockHistory(
                group_id=group_id,
                code=code,
                timestamp=ts,
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=vol,
            ))
            price = close
        self.prices[group_id][code] = price
        self.current_candles[group_id][code]["open"] = price
        self.current_candles[group_id][code]["high"] = price
        self.current_candles[group_id][code]["low"] = price
        self.current_candles[group_id][code]["close"] = price

    def set_main_loop(self, loop):
        self._main_loop = loop

    def drain_pending_news_codes(self):
        items = []
        while not self._pending_llm_news.empty():
            try:
                items.append(self._pending_llm_news.get_nowait())
            except queue_mod.Empty:
                break
        return items

    def get_price_snapshot(self, group_id):
        self.ensure_group_initialized(group_id)
        with self._snapshot_lock:
            snap = self._price_snapshot.get(str(group_id))
            if snap:
                return dict(snap)
        return self._build_price_snapshot(group_id)

    def _build_price_snapshot(self, group_id):
        group_id = str(group_id)
        self.ensure_group_initialized(group_id)
        with self.lock:
            snap = {}
            for code, price in self.prices.get(group_id, {}).items():
                candle = self.current_candles[group_id][code]
                snap[code] = {
                    "price": float(price),
                    "trend": self.trend_levels[group_id].get(code, 0),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle["volume"] + candle["simulated_volume"]),
                }
        with self._snapshot_lock:
            self._price_snapshot[group_id] = snap
        return dict(snap)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

    def set_open(self, is_open: bool):
        self.manual_override = is_open
        self.is_open = is_open

    def _check_market_hours(self):
        now = get_china_time()
        if now.weekday() >= 5:
            return False
        current_time = now.time()
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("11:30", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("15:00", "%H:%M").time()
        return (morning_start <= current_time <= morning_end) or (afternoon_start <= current_time <= afternoon_end)

    def _loop(self):
        while self.running:
            try:
                if self.trading_hours:
                    should_be_open = self._check_market_hours()
                    self.is_open = self.manual_override if self.manual_override is not None else should_be_open

                if not self.is_open:
                    time.sleep(1)
                    continue

                now_ts = time.time()
                if now_ts - self.last_update_time >= self.update_interval:
                    self.last_update_time = now_ts
                    self.update_count += 1
                    for group_id in list(self.prices.keys()):
                        self._refresh_all_tech_levels(group_id)
                        self._update_prices(group_id)
                        self._save_candles(group_id)
                        if self.news_enabled and self.news_generator and random.random() < self.news_trigger_prob:
                            codes = list(self.prices.get(group_id, {}).keys())
                            if codes:
                                if self.news_generator.news_source in ("llm", "both"):
                                    self._pending_llm_news.put((group_id, random.choice(codes)))
                                    if self._main_loop and self._main_loop.is_running():
                                        try:
                                            asyncio.run_coroutine_threadsafe(
                                                self._async_process_llm_news(), self._main_loop
                                            )
                                        except Exception:
                                            pass
                                else:
                                    self._generate_news(group_id)
                time.sleep(1)
            except Exception as e:
                print(f"[FinCenter] Stock market loop error: {e}")
                time.sleep(5)

    def _calc_trend_change(self, trend_level, volatility):
        if not self.trend_enabled:
            return random.gauss(0, volatility)
        low, high = TREND_BASE_RANGES.get(trend_level, (-0.005, 0.005))
        return random.uniform(low, high) + random.gauss(0, volatility * 0.3)

    def _calc_mean_reversion(self, group_id, code, price):
        base_price = self.base_prices.get(group_id, {}).get(code)
        if not base_price or base_price <= 0:
            return 0.0
        deviation = (price - base_price) / base_price
        return -TREND_REVERSION_FACTOR * deviation

    def _simulate_intra_period(self, open_price, total_change, volatility, steps=INTRA_PERIOD_STEPS):
        price = open_price
        high = open_price
        low = open_price
        total_change = max(-0.95, total_change)
        step_drift = math.log1p(total_change) / steps
        step_vol = volatility / math.sqrt(steps)
        for i in range(steps):
            progress = (i + 1) / steps
            drift = step_drift * (1.0 - 0.3 * math.sin(math.pi * progress))
            noise = random.gauss(0, step_vol)
            micro_momentum = 0.0
            if i > 0:
                prev_change = (price - open_price) / open_price
                micro_momentum = prev_change * 0.05 * random.choice([-1, 1])
            price *= math.exp(drift + noise + micro_momentum)
            price = max(0.01, price)
            high = max(high, price)
            low = min(low, price)
        return high, low, price

    def _simulate_volume(self, code, price_change_pct, trend_level, liquidity=1.0, active_news=False, breakout=False):
        base_volume = random.uniform(VOLUME_BASE_MIN, VOLUME_BASE_MAX)
        volatility_factor = 1.0 + abs(price_change_pct) * VOLUME_VOLATILITY_SENSITIVITY
        abs_trend = abs(trend_level)
        trend_factor = VOLUME_TREND_MULTIPLIER if abs_trend >= 2 else 1.0
        news_factor = 1.8 if active_news else 1.0
        breakout_factor = 1.6 if breakout else 1.0
        noise = max(0.3, min(2.5, random.gauss(1.0, 0.15)))
        return base_volume * volatility_factor * trend_factor * news_factor * breakout_factor * liquidity * noise

    @staticmethod
    def _clamp_change(change, limit):
        return max(-limit, min(limit, change))

    def _is_breakout(self, group_id, code, old_price, new_price):
        tech = self.tech_states.get(group_id, {}).get(code)
        if not tech:
            return False
        crossed_resistance = tech.resistance and old_price < tech.resistance <= new_price
        crossed_support = tech.support and old_price > tech.support >= new_price
        return bool(crossed_resistance or crossed_support)

    def _apply_technical_adjustment(self, group_id, code, price, trend_level):
        if not self.tech_enabled:
            return 0.0
        tech = self.tech_states.get(group_id, {}).get(code)
        if not tech:
            return 0.0
        adjustment = 0.0
        if tech.resistance and price >= tech.resistance * 0.97 and trend_level > 0:
            adjustment -= 0.01
            if random.random() < 0.3:
                tech.peak_detected = True
        if tech.support and price <= tech.support * 1.03 and trend_level < 0:
            adjustment += 0.01
            if random.random() < 0.3:
                tech.trough_detected = True
        if tech.peak_detected and trend_level >= 2:
            adjustment -= 0.02
            tech.peak_detected = False
        if tech.trough_detected and trend_level <= -2:
            adjustment += 0.02
            tech.trough_detected = False
        if tech.bollinger_upper and price >= tech.bollinger_upper:
            adjustment -= 0.005
        if tech.bollinger_lower and price <= tech.bollinger_lower:
            adjustment += 0.005
        return adjustment

    def _find_local_extrema(self, values, window=3):
        maxima = []
        minima = []
        for i in range(window, len(values) - window):
            is_max = all(values[i] >= values[i + j] for j in range(-window, window + 1) if j != 0)
            is_min = all(values[i] <= values[i + j] for j in range(-window, window + 1) if j != 0)
            if is_max:
                maxima.append(values[i])
            if is_min:
                minima.append(values[i])
        return maxima, minima

    def _update_tech_levels(self, group_id, code):
        with self.db.session_scope() as session:
            history = session.query(StockHistory).filter_by(
                group_id=group_id, code=code
            ).order_by(StockHistory.timestamp.desc()).limit(30).all()
            tech = self.tech_states.get(group_id, {}).get(code)
            if not tech or len(history) < 5:
                return
            highs = [h.high for h in history]
            lows = [h.low for h in history]
            closes = [h.close for h in history]
            local_maxima, local_minima = self._find_local_extrema(closes, window=2)
            tech.local_maxima = local_maxima
            tech.local_minima = local_minima
            tech.resistance = (sum(sorted(local_maxima, reverse=True)[:2]) / len(sorted(local_maxima, reverse=True)[:2]) * 0.99) if local_maxima else max(highs) * 0.98
            tech.support = (sum(sorted(local_minima)[:2]) / len(sorted(local_minima)[:2]) * 1.01) if local_minima else min(lows) * 1.02
            if len(closes) >= 20:
                ma20 = sum(closes[:20]) / 20
                std20 = math.sqrt(sum((c - ma20) ** 2 for c in closes[:20]) / 20)
                tech.bollinger_mid = ma20
                tech.bollinger_upper = ma20 + 2 * std20
                tech.bollinger_lower = ma20 - 2 * std20

    def _refresh_all_tech_levels(self, group_id):
        for code in list(self.prices.get(group_id, {}).keys()):
            self._update_tech_levels(group_id, code)

    def _markov_transition(self, current_trend, duration=0):
        transitions = dict(TREND_TRANSITIONS.get(current_trend, {0: 1.0}))
        if duration > TREND_MAX_DURATION:
            revert_prob = min(0.6, 0.1 * (duration - TREND_MAX_DURATION))
            if current_trend > 0:
                for t in range(current_trend - 1, -4, -1):
                    if t in transitions:
                        transitions[t] = transitions.get(t, 0) + revert_prob / max(1, abs(current_trend - t))
                        break
            elif current_trend < 0:
                for t in range(current_trend + 1, 4):
                    if t in transitions:
                        transitions[t] = transitions.get(t, 0) + revert_prob / max(1, abs(current_trend - t))
                        break
            transitions[0] = transitions.get(0, 0) + revert_prob * 0.5
        targets = list(transitions.keys())
        weights = list(transitions.values())
        total = sum(weights)
        weights = [w / total for w in weights]
        return random.choices(targets, weights=weights, k=1)[0]

    def _update_prices(self, group_id):
        self.ensure_group_initialized(group_id)
        db_updates = {}
        active_events_cache = {}
        if self.news_enabled and self.news_generator:
            for code in list(self.prices[group_id].keys()):
                active_events_cache[code] = self.news_generator.get_active_events(group_id, code)

        with self.lock:
            prices = self.prices[group_id]
            trends = self.trend_levels[group_id]
            durations = self.trend_duration[group_id]
            candles = self.current_candles[group_id]
            for code in list(prices.keys()):
                trend_level = trends.get(code, 0)
                durations[code] = durations.get(code, 0) + 1
                event_adjustment = 0.0
                volatility_multiplier = 1.0
                active_events = active_events_cache.get(code, [])
                news_sensitivity = self._company_param(code, "news_sensitivity", 1.0)
                for ev in active_events:
                    remaining = max(1, int(ev.get("remaining_duration", 1)))
                    decay = min(1.0, remaining / 10.0)
                    event_adjustment += (0.005 if ev["trend_shift"] > 0 else (-0.005 if ev["trend_shift"] < 0 else 0)) * decay
                    event_adjustment += float(ev.get("immediate_jump") or 0) * 0.08 * decay
                    volatility_multiplier = max(volatility_multiplier, ev.get("volatility_boost", 1.0))
                base_volatility = self._company_param(code, "volatility", self.volatility)
                effective_volatility = base_volatility * volatility_multiplier
                total_change = (
                    self._calc_trend_change(trend_level, effective_volatility)
                    + self._apply_technical_adjustment(group_id, code, prices[code], trend_level)
                    + event_adjustment * news_sensitivity
                    + self._calc_mean_reversion(group_id, code, prices[code])
                )
                change_limit = self._company_param(code, "event_max_change" if active_events else "max_change", 0.18 if active_events else 0.08)
                total_change = self._clamp_change(total_change, change_limit)
                open_price = prices[code]
                high, low, close_price = self._simulate_intra_period(open_price, total_change, effective_volatility)
                prices[code] = max(0.01, close_price)
                price_change_pct = (close_price - open_price) / open_price if open_price > 0 else 0
                breakout = self._is_breakout(group_id, code, open_price, prices[code])
                liquidity = self._company_param(code, "liquidity", 1.0)
                sim_volume = self._simulate_volume(
                    code, price_change_pct, trend_level,
                    liquidity=liquidity,
                    active_news=bool(active_events),
                    breakout=breakout,
                )
                candle = candles[code]
                candle["high"] = max(candle["high"], high)
                candle["low"] = min(candle["low"], low)
                candle["close"] = prices[code]
                candle["simulated_volume"] += sim_volume
                if self.trend_enabled and random.random() < 0.1:
                    new_trend = self._markov_transition(trend_level, durations.get(code, 0))
                    if new_trend != trend_level:
                        trends[code] = new_trend
                        durations[code] = 0
                db_updates[code] = {"price": prices[code], "trend": trends[code]}

        if self.news_enabled and self.news_generator:
            for code in list(self.prices[group_id].keys()):
                self.news_generator.tick_events(group_id, code)

        with self._snapshot_lock:
            self._price_snapshot.pop(group_id, None)
        if db_updates:
            with self.db.session_scope() as session:
                now = get_china_time()
                for code, upd in db_updates.items():
                    company = session.query(StockCompany).filter_by(group_id=group_id, code=code).first()
                    if company:
                        company.current_price = upd["price"]
                        company.trend_level = upd["trend"]
                        company.last_update = now

    def _save_candles(self, group_id):
        with self.lock:
            now = get_china_time()
            candle_data = {}
            for code in list(self.prices.get(group_id, {}).keys()):
                candle = self.current_candles[group_id][code]
                total_volume = candle["volume"] + candle["simulated_volume"]
                candle_data[code] = {
                    "timestamp": now,
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": total_volume,
                }
                price = self.prices[group_id][code]
                self.current_candles[group_id][code] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 0.0,
                    "simulated_volume": 0.0,
                    "start_time": now,
                }
        with self.db.session_scope() as session:
            for code, cd in candle_data.items():
                session.add(StockHistory(group_id=group_id, code=code, **cd))

    def _generate_news(self, group_id, target_code=None):
        if not self.news_enabled or not self.news_generator:
            return None
        self.ensure_group_initialized(group_id)
        codes = list(self.prices.get(group_id, {}).keys())
        if not codes:
            return None
        code = target_code.upper() if target_code and target_code.upper() in codes else random.choice(codes)
        with self.db.session_scope() as session:
            company = session.query(StockCompany).filter_by(group_id=group_id, code=code).first()
            if not company:
                return None
            news_records = session.query(StockNews).filter_by(
                group_id=group_id, company_code=code
            ).order_by(StockNews.timestamp.desc()).limit(self.news_history_count).all()
            history_news = [{"event_type": n.event_type, "content": n.content} for n in news_records]

        news_result = self.news_generator.generate_news(
            group_id=group_id,
            company_code=code,
            company_name=company.name,
            current_price=self.prices[group_id][code],
            trend_level=self.trend_levels[group_id].get(code, 0),
            description=getattr(company, 'description', ''),
            history_news=history_news,
        )
        if news_result["trend_shift"] != 0:
            with self.lock:
                new_trend = self.trend_levels[group_id].get(code, 0) + news_result["trend_shift"]
                self.trend_levels[group_id][code] = max(-3, min(3, new_trend))
        if news_result["immediate_jump"] != 0:
            with self.lock:
                self.prices[group_id][code] = max(0.01, self.prices[group_id][code] * (1 + news_result["immediate_jump"]))
            with self._snapshot_lock:
                self._price_snapshot.pop(group_id, None)
        return {
            "code": code,
            "name": company.name,
            "content": news_result["content"],
            "event_type": news_result["event_type"].value,
            "broadcast": self.news_broadcast,
        }

    def trigger_news(self, group_id, target_code=None):
        return self._generate_news(group_id, target_code)

    async def _async_process_llm_news(self):
        items = self.drain_pending_news_codes()
        for group_id, code in items:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._generate_news, group_id, code)
            except Exception as e:
                print(f"[FinCenter] Async LLM news error: {e}")

    def execute_buy(self, stock_group_id, account_group_id, user_id, code, amount):
        stock_group_id = str(stock_group_id)
        account_group_id = str(account_group_id)
        code = code.upper()
        self.ensure_group_initialized(stock_group_id)
        if code not in self.prices.get(stock_group_id, {}):
            return {"success": False, "msg": f"股票代码 {code} 不存在"}
        if not self.is_open:
            return {"success": False, "msg": "当前休市中，无法交易"}
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return {"success": False, "msg": "数量必须是数字"}
        if amount <= 0:
            return {"success": False, "msg": "数量必须大于0"}

        with self.lock:
            price = self.prices[stock_group_id][code]
            self.current_candles[stock_group_id][code]["volume"] += amount
            total_cost = price * amount
            fee = total_cost * self.fee_rate
            cost_with_fee = total_cost + fee
            with self.db.session_scope() as session:
                user = session.query(UserAccount).filter_by(group_id=account_group_id, user_id=user_id).first()
                if not user:
                    return {"success": False, "msg": "请先开户"}
                if user.balance < cost_with_fee:
                    return {"success": False, "msg": f"余额不足。需要 {cost_with_fee:.2f}，当前余额 {user.balance:.2f}"}
                user.sub_balance(cost_with_fee)
                user.add_spent(cost_with_fee)
                holding = session.query(StockHolding).filter_by(
                    group_id=stock_group_id, user_id=user_id, code=code
                ).first()
                if holding:
                    total_amount = holding.amount + amount
                    holding.avg_cost = (holding.avg_cost * holding.amount + total_cost) / total_amount
                    holding.amount = total_amount
                else:
                    session.add(StockHolding(
                        group_id=stock_group_id,
                        user_id=user_id,
                        code=code,
                        amount=amount,
                        avg_cost=price,
                    ))
        return {"success": True, "msg": f"买入成功！{code} x {amount:.2f}，成交价 {price:.2f}，手续费 {fee:.2f}，共花费 {cost_with_fee:.2f}", "price": price, "amount": amount, "fee": fee, "total": cost_with_fee}

    def execute_sell(self, stock_group_id, account_group_id, user_id, code, amount):
        stock_group_id = str(stock_group_id)
        account_group_id = str(account_group_id)
        code = code.upper()
        self.ensure_group_initialized(stock_group_id)
        if code not in self.prices.get(stock_group_id, {}):
            return {"success": False, "msg": f"股票代码 {code} 不存在"}
        if not self.is_open:
            return {"success": False, "msg": "当前休市中，无法交易"}
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return {"success": False, "msg": "数量必须是数字"}
        if amount <= 0:
            return {"success": False, "msg": "数量必须大于0"}

        with self.lock:
            price = self.prices[stock_group_id][code]
            self.current_candles[stock_group_id][code]["volume"] += amount
            total_revenue = price * amount
            fee = total_revenue * self.fee_rate
            revenue_after_fee = total_revenue - fee
            with self.db.session_scope() as session:
                holding = session.query(StockHolding).filter_by(
                    group_id=stock_group_id, user_id=user_id, code=code
                ).first()
                if not holding or holding.amount < amount:
                    current = holding.amount if holding else 0
                    return {"success": False, "msg": f"持仓不足。当前持有 {current:.2f} {code}"}
                holding.amount -= amount
                if holding.amount < 0.0001:
                    session.delete(holding)
                user = session.query(UserAccount).filter_by(group_id=account_group_id, user_id=user_id).first()
                if user:
                    user.add_balance(revenue_after_fee)
                    user.add_earned(revenue_after_fee)
        return {"success": True, "msg": f"卖出成功！{code} x {amount:.2f}，成交价 {price:.2f}，手续费 {fee:.2f}，到账 {revenue_after_fee:.2f}", "price": price, "amount": amount, "fee": fee, "total": revenue_after_fee}

    def get_holdings(self, group_id, user_id):
        group_id = str(group_id)
        self.ensure_group_initialized(group_id)
        with self.db.session_scope() as session:
            holdings = session.query(StockHolding).filter_by(group_id=group_id, user_id=user_id).all()
            result = []
            for h in holdings:
                if h.amount > 0.0001:
                    current_price = float(self.prices.get(group_id, {}).get(h.code, 0))
                    amount = float(h.amount)
                    avg_cost = float(h.avg_cost)
                    market_value = amount * current_price
                    profit = (current_price - avg_cost) * amount
                    profit_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
                    result.append({"code": h.code, "amount": amount, "avg_cost": avg_cost, "current_price": current_price, "price": current_price, "market_value": market_value, "profit": profit, "profit_pct": profit_pct})
        return result

    def get_market_status(self, group_id=None):
        group_id = str(group_id or next(iter(self.prices.keys()), ""))
        if group_id:
            self.ensure_group_initialized(group_id)
        status = "开市中" if self.is_open else "休市中"
        lines = [f"📊 股市状态: {status}\n"]
        for code, price in self.prices.get(group_id, {}).items():
            trend = self.trend_levels.get(group_id, {}).get(code, 0)
            trend_name = {3: "🔥强势上涨", 2: "📈稳步上涨", 1: "↗轻微上涨", 0: "➡横盘震荡", -1: "↘轻微下跌", -2: "📉稳步下跌", -3: "💥强势下跌"}.get(trend, "➡横盘震荡")
            lines.append(f"  {code}: {price:.2f} {trend_name}")
        return "\n".join(lines)

    def get_today_news(self, group_id):
        with self.db.session_scope() as session:
            now = get_china_time()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            news_list = session.query(StockNews).filter(
                StockNews.group_id == str(group_id),
                StockNews.timestamp >= today_start,
            ).order_by(StockNews.timestamp.desc()).limit(10).all()
            return [n.to_display_dict() for n in news_list]

    def get_tech_levels(self, group_id, code):
        self.ensure_group_initialized(group_id)
        tech = self.tech_states.get(str(group_id), {}).get(code.upper())
        if not tech:
            return None
        support = [round(float(tech.support), 4)] if tech.support else []
        resistance = [round(float(tech.resistance), 4)] if tech.resistance else []
        return {
            "support": support,
            "resistance": resistance,
            "bollinger_upper": tech.bollinger_upper,
            "bollinger_lower": tech.bollinger_lower,
            "bollinger_mid": tech.bollinger_mid,
        }

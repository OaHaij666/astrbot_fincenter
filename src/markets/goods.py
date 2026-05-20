"""物资市场引擎模块

提供物资市场模拟引擎，包含价格刷新、买卖交易、玩家间交易等功能。
所有数据库操作通过 session_scope() 上下文管理器进行，确保事务安全。
"""
import threading
import time
import random
import uuid
import os

from ..core.database import (
    DB, GoodsDefinition, GoodsMarketPrice, UserBackpack,
    GoodsTradeRequest, UserAccount, get_china_time
)
from ..config import GoodsConfig


class GoodsMarket:
    """物资市场引擎

    管理物资价格模拟、买卖交易和玩家间交易。
    接受类型化的 GoodsConfig 配置对象。
    """

    def __init__(self, db: DB, config: GoodsConfig):
        self.db = db
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        self.refresh_interval = config.goods_refresh_interval
        self.price_volatility = config.goods_price_volatility
        self.user_trade_enabled = config.goods_user_trade_enabled
        self.trade_tax = config.goods_user_trade_tax

        self.last_refresh_time = time.time()

        self._init_market()

    def _init_market(self):
        with self.db.session_scope() as session:
            markets = session.query(GoodsMarketPrice).all()
            if not markets:
                self._refresh_all_prices(session)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def _loop(self):
        while self.running:
            try:
                now_ts = time.time()
                if now_ts - self.last_refresh_time >= self.refresh_interval:
                    self.last_refresh_time = now_ts
                    with self.db.session_scope() as session:
                        self._refresh_all_prices(session)
                time.sleep(60)
            except Exception as e:
                print(f"[FinCenter] Goods market loop error: {e}")
                time.sleep(60)

    def _refresh_all_prices(self, session):
        markets = session.query(GoodsMarketPrice).all()
        for market in markets:
            definition = session.query(GoodsDefinition).filter_by(
                goods_id=market.goods_id
            ).first()
            if definition:
                market.previous_price = market.current_price
                base = definition.base_price
                new_price = base * (1 + random.uniform(-self.price_volatility, self.price_volatility))
                new_price = max(definition.min_price, min(definition.max_price, new_price))
                market.current_price = round(new_price, 2)
                market.last_refresh = get_china_time()

    def add_goods(self, group_id, goods_id, name, icon="📦", base_price=10.0,
                  min_price=None, max_price=None, volatility=0.1, preview_image_path=""):
        if min_price is None:
            min_price = base_price * 0.1
        if max_price is None:
            max_price = base_price * 10.0

        with self.db.session_scope() as session:
            existing = session.query(GoodsDefinition).filter_by(
                group_id=group_id, goods_id=goods_id
            ).first()
            if existing:
                return False

            definition = GoodsDefinition(
                group_id=group_id,
                goods_id=goods_id,
                name=name,
                icon=icon,
                preview_image=preview_image_path,
                min_price=min_price,
                max_price=max_price,
                base_price=base_price,
                volatility=volatility,
            )
            session.add(definition)

            market = GoodsMarketPrice(
                group_id=group_id,
                goods_id=goods_id,
                current_price=base_price,
                previous_price=base_price,
                last_refresh=get_china_time(),
            )
            session.add(market)

        return True

    def set_goods_price(self, group_id, goods_id, price):
        with self.db.session_scope() as session:
            definition = session.query(GoodsDefinition).filter_by(
                group_id=group_id, goods_id=goods_id
            ).first()
            if not definition:
                return False

            market = session.query(GoodsMarketPrice).filter_by(
                group_id=group_id, goods_id=goods_id
            ).first()
            if market:
                market.current_price = price

        return True

    def set_goods_volatility(self, group_id, goods_id, volatility):
        with self.db.session_scope() as session:
            definition = session.query(GoodsDefinition).filter_by(
                group_id=group_id, goods_id=goods_id
            ).first()
            if not definition:
                return {"success": False, "msg": f"物资 ID '{goods_id}' 不存在"}

            base = definition.base_price
            new_half_range = base * volatility
            definition.min_price = max(0.01, base - new_half_range)
            definition.max_price = base + new_half_range

            name = definition.name
            min_p = definition.min_price
            max_p = definition.max_price

        return {"success": True, "msg": f"物资 '{name}' 波动率已设置为 {volatility:.2f}，价格范围调整为 {min_p:.2f}~{max_p:.2f}"}

    def remove_goods(self, group_id, goods_id):
        with self.db.session_scope() as session:
            definition = session.query(GoodsDefinition).filter_by(
                group_id=group_id, goods_id=goods_id
            ).first()
            if not definition:
                return False

            session.query(GoodsMarketPrice).filter_by(
                group_id=group_id, goods_id=goods_id
            ).delete()

            backpacks = session.query(UserBackpack).filter_by(
                group_id=group_id, goods_id=goods_id
            ).all()
            for bp in backpacks:
                market = session.query(GoodsMarketPrice).filter_by(
                    group_id=group_id, goods_id=goods_id
                ).first()
                refund = bp.amount * (market.current_price if market else 0)
                if refund > 0:
                    user = session.query(UserAccount).filter_by(
                        group_id=group_id, user_id=bp.user_id
                    ).first()
                    if user:
                        user.balance += refund
                session.delete(bp)

            preview_image = definition.preview_image
            session.delete(definition)

        if preview_image and os.path.exists(preview_image):
            try:
                os.remove(preview_image)
            except Exception:
                pass

        return True

    def update_goods_image(self, group_id, goods_id, image_path):
        with self.db.session_scope() as session:
            definition = session.query(GoodsDefinition).filter_by(
                group_id=group_id, goods_id=goods_id
            ).first()
            if not definition:
                return False
            definition.preview_image = image_path
        return True

    def buy_goods(self, group_id, user_id, goods_id, amount):
        with self.lock:
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return {"success": False, "msg": "数量必须是数字"}

            if amount <= 0:
                return {"success": False, "msg": "数量必须大于0"}

            with self.db.session_scope() as session:
                market = session.query(GoodsMarketPrice).filter_by(
                    group_id=group_id, goods_id=goods_id
                ).first()
                if not market:
                    return {"success": False, "msg": f"物资 '{goods_id}' 不存在"}

                total_cost = market.current_price * amount

                user = session.query(UserAccount).filter_by(
                    group_id=group_id, user_id=user_id
                ).first()
                if not user:
                    return {"success": False, "msg": "请先开户"}

                if user.balance < total_cost:
                    return {"success": False, "msg": f"余额不足。需要 {total_cost:.2f}，当前余额 {user.balance:.2f}"}

                user.balance -= total_cost
                user.total_spent += total_cost

                backpack = session.query(UserBackpack).filter_by(
                    group_id=group_id, user_id=user_id, goods_id=goods_id
                ).first()
                if backpack:
                    backpack.amount += amount
                else:
                    backpack = UserBackpack(
                        group_id=group_id,
                        user_id=user_id,
                        goods_id=goods_id,
                        amount=amount,
                    )
                    session.add(backpack)

                price = market.current_price

            return {
                "success": True,
                "msg": f"买入成功！{goods_id} x {amount:.2f}，单价 {price:.2f}，共花费 {total_cost:.2f}",
                "price": price,
                "amount": amount,
                "total": total_cost,
            }

    def sell_goods(self, group_id, user_id, goods_id, amount):
        with self.lock:
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return {"success": False, "msg": "数量必须是数字"}

            if amount <= 0:
                return {"success": False, "msg": "数量必须大于0"}

            with self.db.session_scope() as session:
                market = session.query(GoodsMarketPrice).filter_by(
                    group_id=group_id, goods_id=goods_id
                ).first()
                if not market:
                    return {"success": False, "msg": f"物资 '{goods_id}' 不存在"}

                backpack = session.query(UserBackpack).filter_by(
                    group_id=group_id, user_id=user_id, goods_id=goods_id
                ).first()

                if not backpack or backpack.amount < amount:
                    current = backpack.amount if backpack else 0
                    return {"success": False, "msg": f"背包不足。当前持有 {current:.2f}"}

                total_revenue = market.current_price * amount

                backpack.amount -= amount
                if backpack.amount < 0.0001:
                    session.delete(backpack)

                user = session.query(UserAccount).filter_by(
                    group_id=group_id, user_id=user_id
                ).first()
                if user:
                    user.balance += total_revenue
                    user.total_earned += total_revenue

                price = market.current_price

            return {
                "success": True,
                "msg": f"卖出成功！{goods_id} x {amount:.2f}，单价 {price:.2f}，到账 {total_revenue:.2f}",
                "price": price,
                "amount": amount,
                "total": total_revenue,
            }

    def get_market_list(self, group_id):
        with self.db.session_scope() as session:
            markets = session.query(GoodsMarketPrice).filter_by(group_id=group_id).all()
            result = []
            for m in markets:
                definition = session.query(GoodsDefinition).filter_by(
                    group_id=group_id, goods_id=m.goods_id
                ).first()
                change = 0.0
                if m.previous_price > 0:
                    change = (m.current_price - m.previous_price) / m.previous_price * 100
                result.append({
                    "goods_id": m.goods_id,
                    "name": definition.name if definition else m.goods_id,
                    "icon": definition.icon if definition else "📦",
                    "preview_image": definition.preview_image if definition else "",
                    "current_price": m.current_price,
                    "previous_price": m.previous_price,
                    "base_price": definition.base_price if definition else 0,
                    "change_pct": change,
                    "min_price": definition.min_price if definition else 0,
                    "max_price": definition.max_price if definition else 0,
                })
        return result

    def get_backpack(self, group_id, user_id):
        with self.db.session_scope() as session:
            backpacks = session.query(UserBackpack).filter_by(
                group_id=group_id, user_id=user_id
            ).all()
            result = []
            for bp in backpacks:
                if bp.amount > 0.0001:
                    market = session.query(GoodsMarketPrice).filter_by(
                        group_id=group_id, goods_id=bp.goods_id
                    ).first()
                    definition = session.query(GoodsDefinition).filter_by(
                        group_id=group_id, goods_id=bp.goods_id
                    ).first()
                    current_price = market.current_price if market else 0
                    result.append({
                        "goods_id": bp.goods_id,
                        "name": definition.name if definition else bp.goods_id,
                        "icon": definition.icon if definition else "📦",
                        "amount": bp.amount,
                        "current_price": current_price,
                        "total_value": bp.amount * current_price,
                    })
        return result

    def create_trade_request(self, group_id, from_user, to_user, goods_id, amount, unit_price):
        if not self.user_trade_enabled:
            return {"success": False, "msg": "玩家间交易未启用"}

        try:
            amount = float(amount)
            unit_price = float(unit_price)
        except (ValueError, TypeError):
            return {"success": False, "msg": "数量和单价必须是数字"}

        if amount <= 0 or unit_price <= 0:
            return {"success": False, "msg": "数量和单价必须大于0"}

        with self.db.session_scope() as session:
            backpack = session.query(UserBackpack).filter_by(
                group_id=group_id, user_id=from_user, goods_id=goods_id
            ).first()

            if not backpack or backpack.amount < amount:
                return {"success": False, "msg": "背包中物资不足"}

            trade = GoodsTradeRequest(
                from_user=from_user,
                to_user=to_user,
                group_id=group_id,
                goods_id=goods_id,
                amount=amount,
                unit_price=unit_price,
                status="pending",
            )
            session.add(trade)
            session.flush()
            trade_id = trade.id

        return {"success": True, "msg": f"交易请求已发送，交易ID: {trade_id}", "trade_id": trade_id}

    def accept_trade(self, group_id, user_id, trade_id):
        with self.db.session_scope() as session:
            trade = session.query(GoodsTradeRequest).filter_by(
                id=trade_id, to_user=user_id, group_id=group_id, status="pending"
            ).first()

            if not trade:
                return {"success": False, "msg": "交易请求不存在或已过期"}

            total_cost = trade.amount * trade.unit_price
            fee = total_cost * self.trade_tax
            cost_with_fee = total_cost + fee

            buyer = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not buyer or buyer.balance < cost_with_fee:
                return {"success": False, "msg": f"余额不足。需要 {cost_with_fee:.2f}"}

            seller_backpack = session.query(UserBackpack).filter_by(
                group_id=group_id, user_id=trade.from_user, goods_id=trade.goods_id
            ).first()
            if not seller_backpack or seller_backpack.amount < trade.amount:
                return {"success": False, "msg": "卖家物资不足"}

            seller_backpack.amount -= trade.amount
            if seller_backpack.amount < 0.0001:
                session.delete(seller_backpack)

            buyer.balance -= cost_with_fee

            seller = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=trade.from_user
            ).first()
            if seller:
                seller.balance += total_cost

            buyer_backpack = session.query(UserBackpack).filter_by(
                group_id=group_id, user_id=user_id, goods_id=trade.goods_id
            ).first()
            if buyer_backpack:
                buyer_backpack.amount += trade.amount
            else:
                buyer_backpack = UserBackpack(
                    group_id=group_id,
                    user_id=user_id,
                    goods_id=trade.goods_id,
                    amount=trade.amount,
                )
                session.add(buyer_backpack)

            trade_amount = trade.amount
            trade_goods_id = trade.goods_id
            trade.status = "accepted"

        return {
            "success": True,
            "msg": f"交易完成！获得 {trade_amount:.2f} {trade_goods_id}，花费 {cost_with_fee:.2f}（含手续费 {fee:.2f}）",
        }

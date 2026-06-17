"""账户处理器

处理开户、查询、签到、转账等账户相关指令。
所有数据库操作通过 session_scope() 上下文管理器进行。
"""
import random
from datetime import timedelta

from astrbot.api import logger
from ..core.database import (
    UserAccount, SignInRecord, TransferRecord, get_china_time
)
from ..utils import plotter


class AccountHandler:
    def __init__(self, plugin, html_render):
        self.plugin = plugin

    async def handle_open(self, event, args, group_id, user_id, user_name):
        target_id = None
        if len(args) >= 3:
            raw_id = args[2]
            mentions = event.message_obj.message
            for seg in mentions:
                if hasattr(seg, 'type') and seg.type == 'at':
                    target_id = seg.data.get('qq', '')
                    break
            if not target_id:
                target_id = raw_id

        if target_id:
            if str(target_id) == str(user_id):
                yield event.plain_result("给自己开户请直接使用 /fc open")
                return

            with self.plugin.db.session_scope() as session:
                payer = session.query(UserAccount).filter_by(
                    group_id=group_id, user_id=user_id
                ).first()
                if not payer:
                    yield event.plain_result("你还没有账户，请先 /fc open 开户")
                    return

                if payer.balance < self.plugin.config.currency.open_account_cost:
                    yield event.plain_result(
                        f"余额不足。代开户费用为 {self.plugin.config.currency.open_account_cost:.2f} "
                        f"{self.plugin.config.currency.currency_icon}{self.plugin.config.currency.currency_name}，"
                        f"当前余额 {payer.balance:.2f}"
                    )
                    return

                target_existing = session.query(UserAccount).filter_by(
                    group_id=group_id, user_id=str(target_id)
                ).first()
                if target_existing:
                    yield event.plain_result(f"目标用户 {target_id} 已经有账户了！")
                    return

                payer.balance -= self.plugin.config.currency.open_account_cost

                self.plugin.db.get_or_create_user(
                    session, group_id, str(target_id), str(target_id),
                    self.plugin.config.currency.initial_balance
                )

            yield event.plain_result(
                f"✅ 代开户成功！\n"
                f"为 {target_id} 创建了账户，获得 {self.plugin.config.currency.initial_balance:.2f} "
                f"{self.plugin.config.currency.currency_icon}{self.plugin.config.currency.currency_name}\n"
                f"你支付了 {self.plugin.config.currency.open_account_cost:.2f} "
                f"{self.plugin.config.currency.currency_icon}{self.plugin.config.currency.currency_name} 的手续费"
            )
            return

        with self.plugin.db.session_scope() as session:
            existing = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if existing:
                yield event.plain_result("你已经有账户了！")
                return

            self.plugin.db.get_or_create_user(
                session, group_id, user_id, user_name,
                self.plugin.config.currency.initial_balance
            )

        yield event.plain_result(
            f"✅ 开户成功！获得 {self.plugin.config.currency.initial_balance:.2f} "
            f"{self.plugin.config.currency.currency_icon}{self.plugin.config.currency.currency_name}"
        )

    async def handle_me(self, event, group_id, user_id, user_name, stock_group_id=None, goods_group_id=None, stock_enabled=True, goods_enabled=True):
        with self.plugin.db.session_scope() as session:
            user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not user:
                yield event.plain_result("你还没有账户，请先使用 /fc open 开户")
                return
            user.last_active = get_china_time()

            balance = float(user.balance or 0)
            total_earned = float(user.total_earned or 0)
            total_spent = float(user.total_spent or 0)
            created_at = user.created_at.strftime('%Y-%m-%d') if user.created_at else '未知'

        currency_name = self.plugin.config.currency.currency_name
        currency_icon = self.plugin.config.currency.currency_icon

        holdings = []
        if stock_enabled and stock_group_id and self.plugin.stock_market:
            holdings = self.plugin.stock_market.get_holdings(stock_group_id, user_id)

        backpack = []
        if goods_enabled and goods_group_id and self.plugin.goods_market:
            backpack = self.plugin.goods_market.get_backpack(goods_group_id, user_id)

        result = plotter.render_account_html(
            user_name=user_name,
            balance=balance,
            total_earned=total_earned,
            total_spent=total_spent,
            created_at=created_at,
            currency_name=currency_name,
            currency_icon=currency_icon,
            holdings=holdings,
            backpack=backpack,
        )
        if result:
            html_content, data = result
            image_path = await self.plugin._render_image(html_content, data)
            if image_path:
                yield event.image_result(image_path)
                return

        # 回退纯文本
        msg = f"""👤 {user_name} 的账户
━━━━━━━━━━━━━━
{currency_icon} 余额: {balance:.2f}
📈 累计获得: {total_earned:.2f}
📉 累计消费: {total_spent:.2f}
📅 开户时间: {created_at}"""
        yield event.plain_result(msg)

    async def handle_sign(self, event, group_id, user_id, user_name):
        signin_cfg = self.plugin.config.signin
        if not signin_cfg.signin_enabled:
            yield event.plain_result("签到功能未启用")
            return

        with self.plugin.db.session_scope() as session:
            user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not user:
                yield event.plain_result("你还没有账户，请先使用 /fc open 开户")
                return
            now = get_china_time()
            today = now.strftime('%Y-%m-%d')

            existing = session.query(SignInRecord).filter_by(
                group_id=group_id, user_id=user_id, sign_date=today
            ).first()

            if existing:
                yield event.plain_result("今天已经签到过了！")
                return

            yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
            yesterday_record = session.query(SignInRecord).filter_by(
                group_id=group_id, user_id=user_id, sign_date=yesterday
            ).first()

            consecutive_days = 1
            if yesterday_record:
                consecutive_days = yesterday_record.consecutive_days + 1

            consecutive_days = min(consecutive_days, signin_cfg.signin_max_consecutive)

            reward = signin_cfg.signin_reward_base + random.uniform(0, signin_cfg.signin_reward_var)
            bonus = (consecutive_days - 1) * signin_cfg.signin_consecutive_bonus
            total_reward = reward + bonus

            record = SignInRecord(
                group_id=group_id,
                user_id=user_id,
                sign_date=today,
                reward_amount=total_reward,
                consecutive_days=consecutive_days,
            )
            session.add(record)

            user.add_balance(total_reward)
            user.add_earned(total_reward)

        currency_name = self.plugin.config.currency.currency_name
        currency_icon = self.plugin.config.currency.currency_icon

        # 图片优先
        result = plotter.render_signin_html(
            total_reward=total_reward,
            base_reward=reward,
            consecutive_days=consecutive_days,
            bonus=bonus,
            currency_name=currency_name,
            currency_icon=currency_icon,
        )
        if result:
            html_content, data = result
            image_path = await self.plugin._render_image(html_content, data)
            if image_path:
                yield event.image_result(image_path)
                return

        # 文字回退
        msg = f"""✅ 签到成功！
{currency_icon} 基础奖励: {reward:.2f}
🔥 连续签到: {consecutive_days}天 (额外 +{bonus:.2f})
💰 共获得: {total_reward:.2f} {currency_name}"""

        yield event.plain_result(msg)

    async def handle_transfer(self, event, args, group_id, user_id, user_name):
        if len(args) < 4:
            yield event.plain_result("格式: /fc transfer <@用户> <金额>")
            return

        target_name = args[2]
        try:
            amount = float(args[3])
        except ValueError:
            yield event.plain_result("金额必须是数字")
            return

        if amount <= 0:
            yield event.plain_result("金额必须大于0")
            return

        mentions = event.message_obj.message
        target_id = None
        for seg in mentions:
            if hasattr(seg, 'type') and seg.type == 'at':
                target_id = seg.data.get('qq', '')
                break

        if not target_id:
            yield event.plain_result("请 @目标用户")
            return

        if target_id == user_id:
            yield event.plain_result("不能给自己转账")
            return

        currency_name = self.plugin.config.currency.currency_name

        with self.plugin.db.session_scope() as session:
            from_user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not from_user:
                yield event.plain_result("请先开户")
                return

            if from_user.balance < amount:
                yield event.plain_result(f"余额不足。当前余额 {from_user.balance:.2f}")
                return

            to_user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=target_id
            ).first()
            if not to_user:
                yield event.plain_result("目标用户未开户")
                return

            from_user.sub_balance(amount)
            to_user.add_balance(amount)
            to_user.add_earned(amount)

            record = TransferRecord(
                from_user=user_id,
                to_user=target_id,
                group_id=group_id,
                amount=amount,
                fee=0.0,
            )
            session.add(record)

        yield event.plain_result(f"✅ 转账成功！向 {target_name} 转账 {amount:.2f} {currency_name}")

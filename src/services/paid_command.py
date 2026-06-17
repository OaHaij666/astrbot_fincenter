"""付费指令扣费服务。"""
from ..core.database import PaidCommand, UserAccount


class PaidCommandService:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    def check_and_deduct(self, message: str, group_id: str, user_id: str) -> str | None:
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

            is_admin = str(user_id) in self.config.admin_id_set
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

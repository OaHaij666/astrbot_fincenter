"""付费指令拦截/扣费/退款服务。

工作流程：
1. 高 priority 的 group_message handler 在事件流中先于其他插件命令执行。
2. 命中 PaidCommand 后扣费，成功扣费记录写入 ``event.set_extra("fc_paid_record", ...)``。
3. 事件继续传播给真正提供服务的插件。
4. 如果目标插件 handler 抛异常，AstrBot 会触发 ``OnPluginErrorEvent`` hook，
   本插件的 hook 看到 ``fc_paid_record`` 后调用 ``refund(...)`` 退款。
"""
from decimal import Decimal

from src.core.database import PaidCommand, UserAccount


class PaidCommandService:
    GLOBAL_GROUP = "*"

    def __init__(self, db, config):
        self.db = db
        self.config = config

    # ---- 内部工具 ----
    def _admin_id_set(self):
        return self.config.admin_id_set

    def _strip_wake_prefixes(self, message: str) -> str:
        cfg = self.config.paid_cmd
        for prefix in cfg.paid_cmd_prefixes or []:
            if prefix and message.startswith(prefix):
                return message[len(prefix):].lstrip()
        return message.lstrip()

    def _split_first_token(self, message: str) -> str | None:
        token = message.split(maxsplit=1)
        return token[0] if token else None

    # ---- 查询/CRUD ----
    def _config_paid_commands(self, paid_group_id: str | None = None) -> list[dict]:
        rows = []
        target_groups = {paid_group_id, self.GLOBAL_GROUP} if paid_group_id is not None else None
        for group in getattr(self.config.paid_cmd, "paid_cmd_groups", []) or []:
            group_id = str(group.get("group_id", "")).strip()
            if not group_id:
                continue
            if target_groups is not None and group_id not in target_groups:
                continue
            for cmd in group.get("commands", []) or []:
                command = str(cmd.get("command", "")).strip()
                if not command:
                    continue
                try:
                    cost = float(cmd.get("cost", self.config.paid_cmd.paid_cmd_default_cost))
                except (TypeError, ValueError):
                    cost = float(self.config.paid_cmd.paid_cmd_default_cost)
                rows.append({
                    "id": None,
                    "group_id": group_id,
                    "command": command,
                    "cost": cost,
                    "description": str(cmd.get("description", "")),
                    "enabled": self._to_bool(cmd.get("enabled", True)),
                    "source": "config",
                })
        return rows

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in ("0", "false", "no", "off", "禁用", "否")
        return bool(value)

    def list_paid_commands(self, paid_group_id: str | None = None) -> list[dict]:
        with self.db.session_scope() as session:
            query = session.query(PaidCommand)
            if paid_group_id is not None:
                query = query.filter(PaidCommand.group_id.in_([paid_group_id, self.GLOBAL_GROUP]))
            rows = query.order_by(PaidCommand.group_id, PaidCommand.command).all()
            db_rows = [self._row_to_dict(r) for r in rows]
        return db_rows + self._config_paid_commands(paid_group_id)

    def add_paid_command(self, paid_group_id: str, command: str, cost: float, description: str = "") -> bool:
        command = command.strip()
        if not command or cost < 0:
            return False
        with self.db.session_scope() as session:
            existing = session.query(PaidCommand).filter_by(
                group_id=paid_group_id, command=command
            ).first()
            if existing:
                existing.cost = cost
                existing.description = description or existing.description
                existing.enabled = 1
            else:
                session.add(PaidCommand(
                    group_id=paid_group_id,
                    command=command,
                    cost=cost,
                    description=description,
                    enabled=1,
                ))
        return True

    def remove_paid_command(self, paid_group_id: str, command: str) -> bool:
        with self.db.session_scope() as session:
            row = session.query(PaidCommand).filter_by(
                group_id=paid_group_id, command=command
            ).first()
            if not row:
                return False
            session.delete(row)
        return True

    def toggle_paid_command(self, paid_group_id: str, command: str, enabled: bool) -> bool:
        with self.db.session_scope() as session:
            row = session.query(PaidCommand).filter_by(
                group_id=paid_group_id, command=command
            ).first()
            if not row:
                return False
            row.enabled = 1 if enabled else 0
        return True

    def _row_to_dict(self, row: PaidCommand) -> dict:
        return {
            "id": row.id,
            "group_id": row.group_id,
            "command": row.command,
            "cost": float(row.cost or 0),
            "description": row.description or "",
            "enabled": bool(row.enabled),
        }

    # ---- 拦截扣费/退款 ----
    def find_match(self, message: str, paid_group_id: str) -> dict | None:
        """根据消息匹配付费命令记录；优先群级，回退全局 ``*``。"""
        cfg = self.config.paid_cmd
        if not cfg.paid_cmd_enabled:
            return None
        stripped = self._strip_wake_prefixes(message.strip())
        token = self._split_first_token(stripped)
        if not token:
            return None
        with self.db.session_scope() as session:
            row = session.query(PaidCommand).filter_by(
                group_id=paid_group_id, command=token, enabled=1
            ).first()
            if not row:
                row = session.query(PaidCommand).filter_by(
                    group_id=self.GLOBAL_GROUP, command=token, enabled=1
                ).first()
            if not row:
                for cfg_row in self._config_paid_commands(paid_group_id):
                    if cfg_row["enabled"] and cfg_row["command"] == token:
                        return cfg_row
                return None
            return self._row_to_dict(row)

    def try_deduct(
        self,
        message: str,
        paid_group_id: str,
        account_group_id: str,
        user_id: str,
        feature_config=None,
    ) -> tuple[str, str | None, dict | None]:
        """尝试扣费。

        Returns:
            (status, reply_text, record)

            status:
                - "miss"        无匹配付费命令
                - "ignore_admin" 命中但管理员豁免
                - "no_account"   未开户
                - "insufficient" 余额不足
                - "charged"      已成功扣费

            reply_text:
                如果有提示用户的回复（不足/扣费成功）则返回字符串。

            record:
                扣费成功时返回扣费记录（含 ``cost``, ``user_id``, ``group_id`` 等）。
        """
        match = self.find_match(message, paid_group_id)
        if not match:
            return "miss", None, None

        cfg = self.config.paid_cmd
        is_admin = str(user_id) in self._admin_id_set()
        if is_admin and cfg.paid_cmd_ignore_admin:
            return "ignore_admin", None, None

        cost = float(match["cost"])
        currency_name = (feature_config.currency.currency_name if feature_config else self.config.currency.currency_name)

        with self.db.session_scope() as session:
            user = session.query(UserAccount).filter_by(
                group_id=account_group_id, user_id=user_id
            ).first()
            if not user:
                return "no_account", cfg.paid_cmd_insufficient_msg.format(
                    cost=cost,
                    currency=currency_name,
                    balance=0.0,
                ), None
            if float(user.balance or 0) < cost:
                return "insufficient", cfg.paid_cmd_insufficient_msg.format(
                    cost=cost,
                    currency=currency_name,
                    balance=float(user.balance or 0),
                ), None

            user.sub_balance(cost)
            user.add_spent(cost)
            balance_after = float(user.balance or 0)

        record = {
            "command": match["command"],
            "paid_group_id": paid_group_id,
            "cost": cost,
            "account_group_id": account_group_id,
            "user_id": user_id,
        }
        reply = None
        if cfg.paid_cmd_deduct_msg:
            reply = cfg.paid_cmd_deduct_msg.format(
                cost=cost,
                currency=currency_name,
                balance=balance_after,
            )
        return "charged", reply, record

    def refund(self, record: dict | None) -> bool:
        """退款。失败/异常时返回 False。"""
        if not record:
            return False
        try:
            cost = Decimal(str(record.get("cost", 0)))
        except Exception:
            return False
        if cost <= 0:
            return False

        account_group_id = record.get("account_group_id")
        user_id = record.get("user_id")
        if not account_group_id or not user_id:
            return False

        with self.db.session_scope() as session:
            user = session.query(UserAccount).filter_by(
                group_id=account_group_id, user_id=user_id
            ).first()
            if not user:
                return False
            user.add_balance(cost)
            user.total_spent = (user.total_spent or 0) - cost
        return True

    # ---- 兼容旧接口 ----
    def check_and_deduct(self, message: str, group_id: str, user_id: str) -> str | None:
        """兼容旧接口：仅返回提示文本，不返回扣费记录。"""
        _, reply, _ = self.try_deduct(message, group_id, group_id, user_id)
        return reply

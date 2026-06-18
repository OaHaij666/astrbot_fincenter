"""FinCenter 插件页面后端 API。"""
from quart import jsonify, request

from src.services.command_registry import list_other_plugin_commands


class FinCenterWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register(self):
        names = {self.plugin.name, "FinCenter", "astrbot_plugin_fincenter"}
        for name in names:
            prefix = f"/{name}/paid"
            self.plugin.context.register_web_api(
                f"{prefix}/config", self.get_paid_config, ["GET"], "FinCenter 付费配置"
            )
            self.plugin.context.register_web_api(
                f"{prefix}/binding", self.set_paid_binding, ["POST"], "设置付费组绑定"
            )
            self.plugin.context.register_web_api(
                f"{prefix}/command", self.save_paid_command, ["POST"], "保存付费命令"
            )
            self.plugin.context.register_web_api(
                f"{prefix}/command/remove", self.remove_paid_command, ["POST"], "删除付费命令"
            )
            self.plugin.context.register_web_api(
                f"{prefix}/command/toggle", self.toggle_paid_command, ["POST"], "启停付费命令"
            )
            self.plugin.context.register_web_api(
                f"{prefix}/scan", self.scan_commands, ["GET"], "扫描插件命令"
            )

    async def get_paid_config(self):
        physical_group_id = request.args.get("group_id", "")
        enabled, paid_group_id = self.plugin.get_paid_binding(physical_group_id) if physical_group_id else (True, "")
        rows = self.plugin.paid_command_service.list_paid_commands(paid_group_id or None)
        return jsonify({
            "status": "ok",
            "data": {
                "physical_group_id": physical_group_id,
                "paid_enabled": enabled,
                "paid_group_id": paid_group_id,
                "commands": rows,
                "currency": {
                    "name": self.plugin.config.currency.currency_name,
                    "icon": self.plugin.config.currency.currency_icon,
                },
            },
        })

    async def set_paid_binding(self):
        body = await request.get_json(force=True, silent=True) or {}
        physical_group_id = str(body.get("physical_group_id", "")).strip()
        paid_group_id = str(body.get("paid_group_id") or physical_group_id).strip()
        enabled = bool(body.get("enabled", True))
        if not physical_group_id:
            return jsonify({"status": "error", "message": "physical_group_id 不能为空"})
        self.plugin.set_market_binding(physical_group_id, "paid", paid_group_id, enabled)
        return jsonify({"status": "ok", "data": {"enabled": enabled, "paid_group_id": paid_group_id}})

    async def save_paid_command(self):
        body = await request.get_json(force=True, silent=True) or {}
        paid_group_id = str(body.get("paid_group_id", "")).strip()
        command = str(body.get("command", "")).strip()
        description = str(body.get("description", "")).strip()
        try:
            cost = float(body.get("cost", self.plugin.config.paid_cmd.paid_cmd_default_cost))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "cost 必须是数字"})
        if not paid_group_id or not command:
            return jsonify({"status": "error", "message": "paid_group_id 和 command 不能为空"})
        ok = self.plugin.paid_command_service.add_paid_command(paid_group_id, command, cost, description)
        return jsonify({"status": "ok" if ok else "error", "data": {"ok": ok}})

    async def remove_paid_command(self):
        body = await request.get_json(force=True, silent=True) or {}
        paid_group_id = str(body.get("paid_group_id", "")).strip()
        command = str(body.get("command", "")).strip()
        ok = self.plugin.paid_command_service.remove_paid_command(paid_group_id, command)
        return jsonify({"status": "ok" if ok else "error", "data": {"ok": ok}, "message": "" if ok else "未找到命令"})

    async def toggle_paid_command(self):
        body = await request.get_json(force=True, silent=True) or {}
        paid_group_id = str(body.get("paid_group_id", "")).strip()
        command = str(body.get("command", "")).strip()
        enabled = bool(body.get("enabled", True))
        ok = self.plugin.paid_command_service.toggle_paid_command(paid_group_id, command, enabled)
        return jsonify({"status": "ok" if ok else "error", "data": {"ok": ok}, "message": "" if ok else "未找到命令"})

    async def scan_commands(self):
        return jsonify({"status": "ok", "data": list_other_plugin_commands()})

"""扫描 AstrBot 中已注册的其他插件命令。

通过 ``star_handlers_registry`` 收集所有 ``CommandFilter``，
按 (插件名, 命令名) 输出。本插件自身的命令会被排除。
"""
from __future__ import annotations

from typing import Iterable

try:
    from astrbot.core.star.star_handler import star_handlers_registry, EventType
    from astrbot.core.star.star import star_map
    from astrbot.core.star.filter.command import CommandFilter
    from astrbot.core.star.filter.command_group import CommandGroupFilter
except ImportError:  # pragma: no cover
    star_handlers_registry = None
    star_map = None
    CommandFilter = None
    CommandGroupFilter = None
    EventType = None


SELF_PLUGIN_NAME = "FinCenter"


def _iter_command_names(filter_obj) -> Iterable[str]:
    """把 CommandFilter / CommandGroupFilter 展开成完整命令名列表。"""
    if CommandFilter and isinstance(filter_obj, CommandFilter):
        names = [filter_obj.command_name]
        names.extend(getattr(filter_obj, "alias", set()) or [])
        parents = getattr(filter_obj, "parent_command_names", [""]) or [""]
        for parent in parents:
            for name in names:
                full = name if not parent else f"{parent} {name}"
                yield full.strip()
    elif CommandGroupFilter and isinstance(filter_obj, CommandGroupFilter):
        names = [filter_obj.group_name] if hasattr(filter_obj, "group_name") else []
        names.extend(getattr(filter_obj, "alias", set()) or [])
        for name in names:
            yield name


def list_other_plugin_commands(exclude_plugin: str = SELF_PLUGIN_NAME) -> list[dict]:
    """收集除本插件外的所有命令信息。

    Returns:
        ``[{"plugin": "...", "command": "...", "desc": "..."}]``
    """
    if not star_handlers_registry or not star_map:
        return []

    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for handler in list(star_handlers_registry):
        if EventType and handler.event_type != EventType.AdapterMessageEvent:
            continue
        plugin_md = star_map.get(handler.handler_module_path)
        plugin_name = plugin_md.name if plugin_md else handler.handler_module_path
        if plugin_name == exclude_plugin:
            continue
        for filt in handler.event_filters or []:
            for cmd in _iter_command_names(filt):
                key = (plugin_name, cmd)
                if not cmd or key in seen:
                    continue
                seen.add(key)
                desc = getattr(handler, "desc", "") or ""
                result.append({
                    "plugin": plugin_name,
                    "command": cmd,
                    "desc": desc.split("\n")[0] if desc else "",
                })
    result.sort(key=lambda x: (x["plugin"], x["command"]))
    return result

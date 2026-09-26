"""车辆流转业务规则：转卖交接校验、维修归属政策、通知归属与归属时间线。

规则与存档（transfer_archive.py）、查询页面（static/vehicle.html）分离，
本模块只做判断和推导，不直接操作数据库。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping


class TransferRuleError(Exception):
    """交接规则校验失败，携带 HTTP 状态码和中文提示。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def require_handover_fields(new_owner: str, new_country: str, idempotency_key: str) -> None:
    """交接必填项：幂等键用于重复交接时沿用首次结果。"""
    if not idempotency_key.strip():
        raise TransferRuleError(400, "交接幂等键不能为空")
    if not new_owner.strip() or not new_country.strip():
        raise TransferRuleError(400, "新车主和新国家不能为空")


def require_handover_change(vehicle: Mapping, new_owner: str, new_country: str) -> None:
    """交接必须带来归属变化，否则视为无效交接。"""
    if new_owner == vehicle["owner_name"] and new_country == vehicle["country"]:
        raise TransferRuleError(409, "新车主和新国家与现任相同，交接没有变化")


def normalize_handover_at(handover_at: str, fallback: str) -> str:
    """交接时间缺省取当前时间；显式提供时必须是 ISO 8601，
    统一规范为 UTC 毫秒格式，保证归属时间线可按字符串比较。"""
    stamp = handover_at.strip()
    if not stamp:
        return fallback
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransferRuleError(400, "交接时间必须是 ISO 8601 格式") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def in_progress_repairs(repairs: Iterable[Mapping]) -> list[int]:
    """正在维修（已报修未复核）的单据：车辆转出后原网点继续完成这单，
    已确认的维修同样保留在原网点，档案只记录、不改派。"""
    return [int(repair["id"]) for repair in repairs if repair["status"] == "reported"]


def notification_recipient(vehicle: Mapping) -> dict:
    """下一版本通知的接收归属：始终按车辆当前车主和所在国家发出。"""
    return {"recipient_name": vehicle["owner_name"], "recipient_country": vehicle["country"]}


def ownership_timeline(vehicle: Mapping, transfers: list[Mapping]) -> list[dict]:
    """按时间顺序还原从初始登记到现任车主的完整归属变化。"""
    if transfers:
        first = transfers[0]
        timeline = [{"owner_name": first["from_owner"], "country": first["from_country"],
                     "since": None, "source": "初始登记"}]
    else:
        timeline = [{"owner_name": vehicle["owner_name"], "country": vehicle["country"],
                     "since": None, "source": "初始登记"}]
    for transfer in transfers:
        timeline.append({"owner_name": transfer["to_owner"], "country": transfer["to_country"],
                         "since": transfer["handover_at"], "source": f"交接 #{transfer['id']}"})
    return timeline


def ownership_at(vehicle: Mapping, transfers: list[Mapping], when: str) -> tuple[str, str]:
    """还原某一时刻（如报修时间）的车主和所在国家，用于监管核查责任归属。"""
    if transfers:
        owner, country = transfers[0]["from_owner"], transfers[0]["from_country"]
    else:
        owner, country = vehicle["owner_name"], vehicle["country"]
    for transfer in transfers:
        if transfer["handover_at"] <= when:
            owner, country = transfer["to_owner"], transfer["to_country"]
    return owner, country

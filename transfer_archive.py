"""车辆流转档案：每次转卖的归属变化存档、幂等查询与按车检索。

只负责存储与读取，业务规则见 transfer_rules.py，展示见 static/vehicle.html。
"""
from __future__ import annotations

import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  from_owner TEXT NOT NULL,
  from_country TEXT NOT NULL,
  to_owner TEXT NOT NULL,
  to_country TEXT NOT NULL,
  handover_at TEXT NOT NULL,
  in_progress_repairs TEXT NOT NULL DEFAULT '[]',
  idempotency_key TEXT NOT NULL,
  recorded_by TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  UNIQUE(vehicle_id, idempotency_key)
);
"""


class TransferArchive:
    """车辆流转档案表 vehicle_transfers 的存取入口。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)

    def record(self, *, vehicle_id: int, from_owner: str, from_country: str, to_owner: str, to_country: str,
               handover_at: str, in_progress_repairs: list[int], idempotency_key: str, actor: str, recorded_at: str) -> dict:
        """写入一次转卖交接：原/新车主、原/新国家、交接时间和转出时在修单据。"""
        cur = self.conn.execute(
            """INSERT INTO vehicle_transfers(vehicle_id,from_owner,from_country,to_owner,to_country,handover_at,
                                             in_progress_repairs,idempotency_key,recorded_by,recorded_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (vehicle_id, from_owner, from_country, to_owner, to_country, handover_at,
             json.dumps(in_progress_repairs), idempotency_key, actor, recorded_at))
        row = self.conn.execute("SELECT * FROM vehicle_transfers WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._as_dict(row)

    def find_by_key(self, vehicle_id: int, idempotency_key: str) -> dict | None:
        """按幂等键查首次交接，重复交接沿用首次结果。"""
        row = self.conn.execute("SELECT * FROM vehicle_transfers WHERE vehicle_id=? AND idempotency_key=?",
                                (vehicle_id, idempotency_key)).fetchone()
        return self._as_dict(row) if row else None

    def for_vehicle(self, vehicle_id: int) -> list[dict]:
        """按车辆取全部流转记录，按交接先后排序。"""
        return [self._as_dict(row) for row in self.conn.execute(
            "SELECT * FROM vehicle_transfers WHERE vehicle_id=? ORDER BY id", (vehicle_id,))]

    @staticmethod
    def _as_dict(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["in_progress_repairs"] = json.loads(data["in_progress_repairs"])
        return data

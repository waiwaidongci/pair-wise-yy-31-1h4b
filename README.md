# 车辆安全召回与修复跟踪系统

标准库 Python 3.11+ + SQLite。支持召回草稿、监管审核发布、范围按版本调整、车辆登记与跨境流转、维修网点零件库存、修复证据复核、未完成高风险车辆统计，以及通知和监管上报版本。

车辆转卖会留下流转档案：每次交接保存原车主、原国家、新车主、新国家和交接时间；正在维修的车辆转出后原网点继续完成该单，已确认的维修仍归原网点；未完成车辆随交接归属新车主，下一版本通知按新归属发出。交接按幂等键去重，重复交接沿用首次结果。

业务文件分为三块：`transfer_rules.py`（交接规则与归属推导）、`transfer_archive.py`（流转档案存取）、`static/vehicle.html`（按车辆识别码查询的页面）。

## 运行

```bash
python3 app.py --init --seed
python3 app.py
```

默认端口 `8213`。身份通过 `X-Actor` 与 `X-Role` 请求头模拟，角色为 `manufacturer`、`regulator`、`dealer`。可用 `--port`、`--db` 覆盖。

## 主要接口

- `POST /api/dealers`、`POST /api/vehicles`：登记网点和车辆。
- `POST /api/vehicles/{vin}/transfer`：车辆转卖交接，需 `idempotency_key`，可选 `handover_at`（ISO 8601）；重复交接沿用首次结果。
- `GET /api/vehicles/{vin}/history`：按车辆识别码查看完整流转、维修记录和归属变化时间线。
- `POST /api/recalls`、`POST /api/recalls/{id}/submit`：创建并提交召回。
- `POST /api/recalls/{id}/review`：监管发布或退回。
- `POST /api/recalls/{id}/scope`：调整召回范围并生成新版本通知/上报。
- `POST /api/recalls/{id}/parts`：维修网点入库。
- `POST /api/repairs`、`POST /api/repairs/{id}/review`：报告并复核维修。
- `GET /api/recalls/{id}/unfinished`：查看高风险未完成车辆。
- `GET /api/state`、`GET /api/health`：状态与健康检查。
- `/vehicle`：车辆流转档案查询页面。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

当前为本地原型：跨境规则用许可字符串模拟，零件库存与维修记录是简化模型，不包含真实 VIN 解码、监管接口、物流系统或法定通知渠道。

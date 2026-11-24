"""齐套假绿修复第23号（齐套修辛）——三红失败测源文件。

命运条（甲路径，当班锁死，禁止旁门混用）：
  过磅裁定 -> 封闸升代写最新闸代快照 -> 凭快照放行 -> 对账只认快照齐套。

三红：
  甲 无最新闸代快照时，正式放行必须零增拒写（409，无任何业务行落库）。
  乙 对账/单票证明不得把放行行（影子意图）当快照齐套；混批 BL 一票缺快照即不齐套。
  争用 双会话同票并发抢放行写口，闸口锁只许一个赢家，败方仅留争用痕。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db, now_iso


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t23.db")
    init_db()
    yield


def _auth(c: TestClient, user: str = "admin", password: str = "admin123") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": password}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _lane_id(c: TestClient, h: dict, code: str) -> int:
    lanes = c.get("/api/lanes", headers=h).json()["items"]
    return next(x for x in lanes if x["lane_code"] == code)["id"]


def _weigh(c: TestClient, h: dict, ticket_code: str, bl_ref: str, gross_axles: list):
    lane_id = _lane_id(c, h, "LN-S-01-OUT")
    return c.post(
        "/api/tickets",
        headers=h,
        json={
            "lane_id": lane_id,
            "bl_ref": bl_ref,
            "vehicle_plate": f"测23·{ticket_code[-3:]}",
            "axle_weights": [
                {"axle": i + 1, "w": w} for i, w in enumerate(gross_axles)
            ],
            "ticket_code": ticket_code,
        },
    ).json()


# ---------------------------------------------------------------- 甲：零增拒写

def test_release_without_latest_snapshot_is_zero_growth_rejected():
    """甲：缺最新闸代快照，正式放行零增拒写；补齐快照后才准放行且响应不冒充齐套。"""
    c = TestClient(app)
    h = _auth(c)
    ticket = _weigh(c, h, "WT-KIT23-A", "BL-2026-0102", [6.0, 5.5])
    assert ticket["status"] == "已裁定"

    with connect() as conn:
        releases_before = conn.execute(
            "SELECT COUNT(*) n FROM gate_releases"
        ).fetchone()["n"]
        audits_before = conn.execute(
            "SELECT COUNT(*) n FROM audit_trail WHERE action='gate_release'"
        ).fetchone()["n"]

    res = c.post(
        "/api/gate/release",
        headers=h,
        json={"ticket_id": ticket["id"], "officer": "齐套修辛"},
    )
    assert res.status_code == 409, "无快照放行必须拒写，不得正式放行"
    assert "快照" in res.json()["detail"]

    # 零增：放行行、票态、审计均不得变化
    with connect() as conn:
        mine = conn.execute(
            "SELECT id FROM gate_releases WHERE ticket_id=?", (ticket["id"],)
        ).fetchall()
        assert mine == [], "拒写后不得留下任何放行行"
        assert conn.execute("SELECT COUNT(*) n FROM gate_releases").fetchone()["n"] == releases_before
        assert (
            conn.execute(
                "SELECT COUNT(*) n FROM audit_trail WHERE action='gate_release'"
            ).fetchone()["n"]
            == audits_before
        )
        row = conn.execute(
            "SELECT status, generation FROM weigh_tickets WHERE id=?", (ticket["id"],)
        ).fetchone()
        assert row["status"] == "已裁定"
        assert row["generation"] == 1

    # 补齐最新闸代快照后才准放行；响应须如实呈报快照，不得再带冒充字段 seal_ready
    seal = c.post("/api/seals", headers=h, json={"ticket_id": ticket["id"]})
    assert seal.status_code == 200
    assert seal.json()["generation"] == 2
    ok = c.post(
        "/api/gate/release",
        headers=h,
        json={"ticket_id": ticket["id"], "officer": "齐套修辛"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["snapshot_complete"] is True
    assert "seal_ready" not in body, "禁止再用 seal_ready 冒充齐套"


# ------------------------------------------------ 乙：对账不认放行影子意图

def test_reconcile_never_counts_release_row_as_snapshot_kit():
    """乙：无快照的放行行不得被对账/单票证明计为齐套；混批 BL 一票缺快照即整批不齐套。"""
    c = TestClient(app)
    h = _auth(c)

    # 夹具复现：WT-LN-S-01-IN-001 已放行但全票无 gate_seals（无快照假齐套雷数据）
    seeded = c.get("/api/proof/ticket/WT-LN-S-01-IN-001", headers=h).json()
    assert seeded["released"] is True
    assert seeded["has_seal"] is False, "放行行不等同快照"
    assert seeded["seal_generation"] is None, "不得凭放行伪造闸代"
    assert seeded["snapshot_complete"] is False
    assert seeded["proof_ready"] is False, "无快照严禁出齐套证明"
    assert seeded["coherent"] is False

    recon_seeded = c.get("/api/reconcile/BL-2026-0102", headers=h).json()
    assert recon_seeded["proof_ready"] is False
    assert all(t["snapshot_complete"] is False for t in recon_seeded["tickets"])

    # 混批 BL：A 票封闸齐套，B 票只有放行行无快照 -> 整批仍不得计齐套
    bl = c.post(
        "/api/bl",
        headers=h,
        json={
            "bl_code": "BL-2026-0909",
            "cargo_desc": "齐套修辛混批",
            "declared_gross_t": 23.5,
            "vessel_voyage": "修辛轮/23",
        },
    )
    assert bl.status_code == 200
    ticket_a = _weigh(c, h, "WT-KIT23-BA", "BL-2026-0909", [6.0, 5.75])
    ticket_b = _weigh(c, h, "WT-KIT23-BB", "BL-2026-0909", [5.75, 6.0])
    assert c.post("/api/seals", headers=h, json={"ticket_id": ticket_a["id"]}).status_code == 200

    # 以直库写入模拟历史埋雷数据：B 票放行但无快照（修复后 API 本身已无法造出此态）
    with connect() as conn:
        lane_id = conn.execute(
            "SELECT lane_id FROM weigh_tickets WHERE id=?", (ticket_b["id"],)
        ).fetchone()["lane_id"]
        conn.execute(
            """INSERT INTO gate_releases(ticket_id,lane_id,release_ref,status,officer,released_at)
               VALUES (?,?,?,?,?,?)""",
            (ticket_b["id"], lane_id, f"GR-LEGACY-{ticket_b['id']}", "已放行",
             "历史雷数据", now_iso()),
        )
        conn.execute(
            "UPDATE weigh_tickets SET status='已放行' WHERE id=?", (ticket_b["id"],)
        )
        conn.commit()

    recon = c.get("/api/reconcile/BL-2026-0909", headers=h).json()
    assert recon["balanced"] is True, "账实本身平衡，排除吨数干扰"
    assert recon["proof_ready"] is False, "一票缺最新闸代快照，整批严禁假齐套"
    by_code = {t["ticket_code"]: t for t in recon["tickets"]}
    assert by_code["WT-KIT23-BA"]["snapshot_complete"] is True
    assert by_code["WT-KIT23-BB"]["snapshot_complete"] is False
    assert "WT-KIT23-BB" in recon["proof_blockers"]


# ------------------------------------------------ 争用：双会话同票抢写口

def test_concurrent_sessions_gate_lock_single_winner_contention_trace(monkeypatch):
    """争用：双会话并发抢同一放行写口，只许一个赢家；败方 409 且只记争用痕。"""
    c = TestClient(app)
    h_admin = _auth(c, "admin", "admin123")
    h_writer = _auth(c, "writer", "writer123")

    ticket = _weigh(c, h_admin, "WT-KIT23-LOCK", "BL-2026-0102", [6.0, 5.5])
    seal = c.post("/api/seals", headers=h_admin, json={"ticket_id": ticket["id"]})
    assert seal.status_code == 200
    lock_key = f"gate:{ticket['id']}"

    # 同步点钉在数据库写锁上：让赢家拿到 BEGIN IMMEDIATE 写锁后持锁停顿，
    # 败方在同一时刻抢同一写口，必然在存储层被真实阻塞。
    import locks

    entered = threading.Event()
    proceed = threading.Event()
    real_begin = locks._begin_immediate

    def stalling_begin(conn):
        real_begin(conn)
        if entered.is_set() is False:
            entered.set()  # 只有第一个拿到写锁的赢家在此持锁停顿
            proceed.wait(timeout=10)

    monkeypatch.setattr(locks, "_begin_immediate", stalling_begin)

    outcome: dict[str, object] = {}

    def call(name, headers):
        try:
            r = c.post(
                "/api/gate/release",
                headers=headers,
                json={"ticket_id": ticket["id"], "officer": name},
            )
            outcome[name] = r.status_code
        except Exception as exc:  # 修复前竞态会冒泡 IntegrityError，须显式证伪
            outcome[name] = f"EXC:{exc!r}"

    t_admin = threading.Thread(target=call, args=("admin", h_admin))
    t_writer = threading.Thread(target=call, args=("writer", h_writer))
    t_admin.start()
    assert entered.wait(timeout=10)
    t_writer.start()
    threading.Event().wait(0.5)
    proceed.set()
    t_admin.join(timeout=15)
    t_writer.join(timeout=15)

    # 赢家归属随线程调度，但语义锁死：恰一个 200、一个 409
    assert sorted(outcome.values()) == [200, 409], outcome
    winner = next(name for name, code in outcome.items() if code == 200)
    loser = next(name for name, code in outcome.items() if code == 409)

    with connect() as conn:
        releases = conn.execute(
            "SELECT id, status FROM gate_releases WHERE ticket_id=?", (ticket["id"],)
        ).fetchall()
        assert len(releases) == 1 and releases[0]["status"] == "已放行"
        traces = conn.execute(
            "SELECT actor, action, detail FROM contention_log WHERE lock_key=?",
            (lock_key,),
        ).fetchall()
        assert len(traces) == 1, "败方只许留一条争用痕"
        assert traces[0]["actor"] == loser
        assert traces[0]["action"] == "争用"
        assert winner in traces[0]["detail"]
        status = conn.execute(
            "SELECT status FROM weigh_tickets WHERE id=?", (ticket["id"],)
        ).fetchone()["status"]
        assert status == "已放行"

    via_api = c.get("/api/contention", headers=h_admin).json()["items"]
    assert any(
        x["lock_key"] == lock_key and x["actor"] == loser for x in via_api
    )

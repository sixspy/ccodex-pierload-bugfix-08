"""闸口放行：须无开放超重，且持最新闸代快照（甲路径：无快照零增拒写）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import GateReleaseIn
from seal_svc import ticket_snapshot_complete
from validators import validate_no_open_overload

router = APIRouter(tags=["gate"])


@router.get("/api/gate/releases")
def list_releases(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT g.*, t.ticket_code, t.vehicle_plate, l.lane_code
               FROM gate_releases g
               JOIN weigh_tickets t ON t.id=g.ticket_id
               JOIN weigh_lanes l ON l.id=g.lane_id
               ORDER BY g.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/gate/release")
def release_gate(body: GateReleaseIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"gate:{body.ticket_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            ticket = conn.execute(
                """SELECT t.*, l.id lane_id FROM weigh_tickets t
                   JOIN weigh_lanes l ON l.id=t.lane_id WHERE t.id=?""",
                (body.ticket_id,),
            ).fetchone()
            if not ticket:
                raise HTTPException(404, "过磅票不存在")
            if ticket["status"] == "作废":
                raise HTTPException(409, "票态已锁定")
            if ticket["status"] == "旁路挂起":
                raise HTTPException(409, "旁路挂起须先闭环")
            if ticket["status"] == "已放行":
                raise HTTPException(409, "已放行")
            validate_no_open_overload(conn, body.ticket_id)
            # 命运条甲路径：缺最新闸代快照则正式放行零增拒写，不插任何业务行。
            if not ticket_snapshot_complete(conn, dict(ticket)):
                raise HTTPException(
                    409,
                    "缺最新闸代快照，禁止放行（零增拒写）：请先封闸写入同代快照",
                )
            if ticket["status"] != "已封闸":
                raise HTTPException(409, "票态不允许放行：须先封闸生成最新闸代快照")
            exists = conn.execute(
                "SELECT id FROM gate_releases WHERE ticket_id=? AND status='已放行'",
                (body.ticket_id,),
            ).fetchone()
            if exists:
                raise HTTPException(409, "已放行")
            now = now_iso()
            ref = f"GR-{ticket['ticket_code']}-{now[:10]}"
            cur = conn.execute(
                """INSERT INTO gate_releases(ticket_id,lane_id,release_ref,status,officer,released_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    body.ticket_id,
                    ticket["lane_id"],
                    ref,
                    "已放行",
                    body.officer,
                    now,
                ),
            )
            conn.execute(
                "UPDATE weigh_tickets SET status='已放行' WHERE id=?",
                (body.ticket_id,),
            )
            write_audit(
                conn,
                user,
                "gate_release",
                ref,
                {"release_id": cur.lastrowid, "ticket_id": body.ticket_id},
            )
            conn.commit()
            # 齐套只由真实同代快照证明，放行响应如实呈报，不再冒充 seal_ready。
            return {
                "id": cur.lastrowid,
                "release_ref": ref,
                "status": "已放行",
                "snapshot_complete": True,
            }
        finally:
            release(conn, lock_key, user)
"""码头锁与争用登记（写入路径嵌入）。"""
from __future__ import annotations

import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit

router = APIRouter(tags=["locks"])

# 争用探测：轮询数据库写锁的间隔与总等待上限（秒）。
_BLOCK_POLL_SECONDS = 0.02
_BLOCK_BUDGET_SECONDS = 30.0

# 进程内各写口的在途写意图持有者。BEGIN IMMEDIATE 在存储层把同写口并发写
# 串行化，但败方在赢家提交后才拿到写锁、已读不到行锁；以此登记让阻塞过的
# 败方仍能识别自己属于并发争用，而非正常串行来单。
_write_intents: dict[str, str] = {}
_intent_guard = threading.Lock()


class LockIn(BaseModel):
    lock_key: str
    action: str = "acquire"


def _record_contention(conn, lock_key: str, holder: str, detail: str) -> None:
    """败方只记争用痕并独立落库；调用方随后抛 409，业务零写入。"""
    conn.execute(
        """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
           VALUES (?,?,?,?,?)""",
        (lock_key, holder, "争用", detail, now_iso()),
    )
    conn.commit()


def _begin_immediate(conn):
    """取得数据库级写锁；独立成函数以便并发测试注入持锁停顿。"""
    conn.execute("BEGIN IMMEDIATE")


def try_acquire(conn, lock_key: str, holder: str) -> bool:
    """争闸口写口。

    双会话同票并发时，BEGIN IMMEDIATE 在数据库写锁上把两个写事务串行化：
    先到者持写锁完成业务并登记在途意图；后到者被写锁阻塞（实际 locked），
    待先到者提交释放后才能继续——此时凭在途意图登记判其为争用败方，
    只记一条争用痕并返回失败，业务零写入。正常串行来单未被阻塞、意图已清，
    不记争用。
    """
    conn.commit()
    blocked = False
    deadline = time.monotonic() + _BLOCK_BUDGET_SECONDS
    while True:
        try:
            _begin_immediate(conn)
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            blocked = True
            if time.monotonic() >= deadline:
                _record_contention(conn, lock_key, holder, "写口忙=等待超时")
                return False
            time.sleep(_BLOCK_POLL_SECONDS)
    # 写锁已取得。曾被阻塞即说明同写口有并发先到写事务，判争用败方。
    if blocked:
        with _intent_guard:
            owner = _write_intents.get(lock_key, "未知")
        _record_contention(conn, lock_key, holder, f"写口忙=并发写锁,持有者={owner}")
        return False
    # 未阻塞：正常取得写口。登记在途意图，行锁随业务事务持有至 release。
    with _intent_guard:
        owner = _write_intents.get(lock_key)
        if owner is not None and owner != holder:
            _record_contention(conn, lock_key, holder, f"持有者={owner}")
            return False
        _write_intents[lock_key] = holder
    row = conn.execute(
        "SELECT holder FROM pier_locks WHERE lock_key=?", (lock_key,)
    ).fetchone()
    if row is None:
        try:
            conn.execute(
                "INSERT INTO pier_locks(lock_key,holder,acquired_at) VALUES (?,?,?)",
                (lock_key, holder, now_iso()),
            )
            return True
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT holder FROM pier_locks WHERE lock_key=?", (lock_key,)
            ).fetchone()
            owner = row["holder"] if row else "未知"
            _record_contention(conn, lock_key, holder, f"持有者={owner}")
            return False
    if row["holder"] == holder:
        return True
    _record_contention(conn, lock_key, holder, f"持有者={row['holder']}")
    return False


def release(conn, lock_key: str, holder: str) -> None:
    # 在途意图保留至写锁释放之后：并发败方在赢家提交后才拿到数据库写锁，
    # 需凭此意图识别争用；下一同写口成功写会自然覆盖该登记。
    conn.execute(
        "DELETE FROM pier_locks WHERE lock_key=? AND holder=?",
        (lock_key, holder),
    )


def require_lock(conn, lock_key: str, holder: str) -> None:
    if not try_acquire(conn, lock_key, holder):
        raise HTTPException(409, "争用：后到只记争用，不写业务")


@router.get("/api/locks")
def list_locks(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pier_locks ORDER BY acquired_at DESC"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/contention")
def list_contention(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contention_log ORDER BY id DESC LIMIT 200"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/locks/acquire")
def acquire_lock(body: LockIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        ok = try_acquire(conn, body.lock_key, user)
        write_audit(conn, user, "lock_acquire", body.lock_key, {"ok": ok})
        conn.commit()
        if not ok:
            raise HTTPException(409, "争用：未能获得锁")
        return {"ok": True, "lock_key": body.lock_key, "holder": user}


@router.post("/api/locks/release")
def release_lock(body: LockIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        release(conn, body.lock_key, user)
        write_audit(conn, user, "lock_release", body.lock_key, {})
        conn.commit()
        return {"ok": True}
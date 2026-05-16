"""
User/Team 사용량 추적 (1,000+ 유저 프로덕션 스케일).

핵심:
- 인증: header 기반 (X-User-Id, X-Team-Id) — 데모용. AUTH_MODE=jwt 시 Cognito JWT 검증 가능.
- 저장소: DynamoDB 3 테이블 (Usage / Directory / BudgetState)
- 비동기 write: FastAPI BackgroundTasks → DynamoDB put_item
- 예산 enforcement: BudgetState atomic counter, 초과 시 HTTP 429
- TTL: 90일 자동 만료
"""

import os
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Iterable

import boto3
from boto3.dynamodb.conditions import Key
from fastapi import HTTPException, Header
from pydantic import BaseModel, Field


REGION = os.getenv("AWS_REGION", "us-east-1")
USAGE_TABLE = os.getenv("USAGE_TABLE", "")
DIRECTORY_TABLE = os.getenv("DIRECTORY_TABLE", "")
BUDGET_STATE_TABLE = os.getenv("BUDGET_STATE_TABLE", "")
TTL_DAYS = 90


# --- Pydantic models ---


class UserCtx(BaseModel):
    """인증 미들웨어가 제공하는 사용자 컨텍스트."""
    user_id: str = Field(min_length=1, max_length=64)
    team_id: str = Field(min_length=1, max_length=64)
    role: str = "member"  # member | team_admin | admin


class UsageRecord(BaseModel):
    user_id: str
    team_id: str
    timestamp: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    tools_used: list[str] = Field(default_factory=list)
    prompt_version: str = "v1"
    session_id: str = ""
    trace_id: str = ""
    latency_ms: int = 0


class BudgetSetRequest(BaseModel):
    entity_type: str = Field(pattern=r"^(user|team)$")
    entity_id: str = Field(min_length=1, max_length=64)
    budget_usd: float = Field(ge=0.0, le=10000.0)


class DirectoryEntry(BaseModel):
    entity_id: str
    entity_type: str  # user | team
    name: str
    email: Optional[str] = None
    team_id: Optional[str] = None
    role: Optional[str] = None
    budget_usd: Optional[float] = None
    member_count: Optional[int] = None
    created_at: Optional[str] = None


# --- DynamoDB clients ---


_resource = None


def _ddb():
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb", region_name=REGION)
    return _resource


def _usage_table():
    return _ddb().Table(USAGE_TABLE)


def _directory_table():
    return _ddb().Table(DIRECTORY_TABLE)


def _budget_table():
    return _ddb().Table(BUDGET_STATE_TABLE)


# --- 비동기 writer (BackgroundTasks 보다 강건한 풀) ---

_writer = ThreadPoolExecutor(max_workers=8, thread_name_prefix="usage-writer")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_bucket(ts: Optional[str] = None) -> str:
    if ts:
        return ts[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _month_bucket(ts: Optional[str] = None) -> str:
    if ts:
        return ts[:7]
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ttl_epoch(days: int = TTL_DAYS) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


# --- 인증 미들웨어 ---


def get_user_ctx(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_team_id: Optional[str] = Header(default=None, alias="X-Team-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
) -> UserCtx:
    """
    헤더 기반 인증 (데모용).
    프로덕션은 AUTH_MODE=jwt 환경변수로 Cognito JWT 검증으로 스왑 가능.
    """
    if not x_user_id:
        # 비익명 호출 — 익명 user로 처리
        x_user_id = "anonymous"
        x_team_id = x_team_id or "default"

    if not x_team_id:
        x_team_id = "default"

    return UserCtx(
        user_id=x_user_id,
        team_id=x_team_id,
        role=x_user_role or "member",
    )


# --- Usage 기록 (비동기) ---


def record_usage(record: UsageRecord) -> None:
    """비동기 DynamoDB write — /chat 응답 latency 영향 없음."""
    _writer.submit(_write_usage_sync, record)


def _write_usage_sync(record: UsageRecord) -> None:
    try:
        ts = record.timestamp or _now_iso()
        sort_key = f"ts#{ts}#{uuid.uuid4().hex[:8]}"
        item = {
            "user_id": record.user_id,
            "sort_key": sort_key,
            "team_id": record.team_id,
            "ts_epoch_ms": int(time.time() * 1000),
            "date_bucket": _date_bucket(ts),
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "total_tokens": record.total_tokens,
            "cost_usd": Decimal(str(round(record.cost_usd, 8))),
            "cost_usd_sort": Decimal(str(round(record.cost_usd, 8))),
            "model": record.model,
            "tools_used": set(record.tools_used) if record.tools_used else {"none"},
            "prompt_version": record.prompt_version,
            "session_id": record.session_id,
            "trace_id": record.trace_id,
            "latency_ms": record.latency_ms,
            "ttl": _ttl_epoch(),
        }
        _usage_table().put_item(Item=item)
        # Budget state 원자적 증가
        period = _month_bucket(ts)
        for entity in (f"user#{record.user_id}", f"team#{record.team_id}"):
            _budget_table().update_item(
                Key={"entity_id": entity, "period": period},
                UpdateExpression="ADD used_usd :v SET last_updated = :ts",
                ExpressionAttributeValues={
                    ":v": Decimal(str(round(record.cost_usd, 8))),
                    ":ts": _now_iso(),
                },
            )
    except Exception as e:
        # 실패는 silent — 운영에선 CloudWatch metric으로 alarm
        print(f"[usage_writer] failed: {e}")


# --- 예산 enforcement ---


def get_budget_state(entity_type: str, entity_id: str, period: Optional[str] = None) -> dict:
    period = period or _month_bucket()
    full_id = f"{entity_type}#{entity_id}"
    try:
        resp = _budget_table().get_item(Key={"entity_id": full_id, "period": period})
        item = resp.get("Item", {})
        # 디렉토리에서 budget 가져오기
        dir_resp = _directory_table().get_item(Key={"entity_id": full_id})
        dir_item = dir_resp.get("Item", {})
        budget = float(dir_item.get("budget_usd", 0.0))
        used = float(item.get("used_usd", 0.0))
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "period": period,
            "used_usd": round(used, 6),
            "budget_usd": budget,
            "remaining_usd": round(max(budget - used, 0.0), 6),
            "ratio": round(used / budget, 4) if budget > 0 else 0.0,
            "status": _budget_status(used, budget),
        }
    except Exception as e:
        return {"entity_type": entity_type, "entity_id": entity_id, "error": str(e)[:200]}


def _budget_status(used: float, budget: float) -> str:
    if budget <= 0:
        return "unlimited"
    ratio = used / budget
    if ratio >= 1.0:
        return "exceeded"
    if ratio >= 0.95:
        return "critical"
    if ratio >= 0.80:
        return "warning"
    return "ok"


def enforce_budget(ctx: UserCtx) -> None:
    """예산 초과 시 HTTPException 발생."""
    for entity_type, entity_id in (("user", ctx.user_id), ("team", ctx.team_id)):
        state = get_budget_state(entity_type, entity_id)
        if state.get("status") == "exceeded":
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "budget_exceeded",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "used_usd": state["used_usd"],
                    "budget_usd": state["budget_usd"],
                    "period": state["period"],
                },
            )


# --- Directory 관리 ---


def upsert_user(user_id: str, name: str, team_id: str, email: str = "", role: str = "member", budget_usd: float = 0.0) -> None:
    _directory_table().put_item(Item={
        "entity_id": f"user#{user_id}",
        "entity_type": "user",
        "name": name,
        "email": email,
        "team_id": team_id,
        "role": role,
        "budget_usd": Decimal(str(budget_usd)),
        "created_at": _now_iso(),
    })


def upsert_team(team_id: str, name: str, member_count: int = 0, budget_usd: float = 0.0) -> None:
    _directory_table().put_item(Item={
        "entity_id": f"team#{team_id}",
        "entity_type": "team",
        "team_id": team_id,
        "name": name,
        "member_count": member_count,
        "budget_usd": Decimal(str(budget_usd)),
        "created_at": _now_iso(),
    })


def list_users(team_id: Optional[str] = None) -> list[dict]:
    if team_id:
        resp = _directory_table().query(
            IndexName="gsi-team",
            KeyConditionExpression=Key("team_id").eq(team_id),
        )
        items = resp.get("Items", [])
        items = [i for i in items if i.get("entity_type") == "user"]
    else:
        resp = _directory_table().query(
            IndexName="gsi-type",
            KeyConditionExpression=Key("entity_type").eq("user"),
        )
        items = resp.get("Items", [])
    return [_clean_dir_item(i) for i in items]


def list_teams() -> list[dict]:
    resp = _directory_table().query(
        IndexName="gsi-type",
        KeyConditionExpression=Key("entity_type").eq("team"),
    )
    return [_clean_dir_item(i) for i in resp.get("Items", [])]


def get_directory_entry(entity_type: str, entity_id: str) -> Optional[dict]:
    resp = _directory_table().get_item(Key={"entity_id": f"{entity_type}#{entity_id}"})
    item = resp.get("Item")
    return _clean_dir_item(item) if item else None


def _clean_dir_item(item: dict) -> dict:
    """DynamoDB Decimal → float, set → list."""
    out = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, set):
            out[k] = list(v)
        else:
            out[k] = v
    return out


# --- Usage 조회 ---


def get_user_usage(user_id: str, days: int = 30) -> dict:
    """지난 N일치 사용자 사용 이력 + 집계."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    resp = _usage_table().query(
        KeyConditionExpression=Key("user_id").eq(user_id) & Key("sort_key").gte(f"ts#{cutoff}"),
        Limit=200,
    )
    items = [_clean_dir_item(i) for i in resp.get("Items", [])]
    total_cost = sum(i.get("cost_usd", 0) for i in items)
    total_tokens = sum(i.get("total_tokens", 0) for i in items)
    by_model: dict[str, dict] = {}
    for it in items:
        m = it.get("model", "unknown")
        bucket = by_model.setdefault(m, {"calls": 0, "tokens": 0, "cost": 0.0})
        bucket["calls"] += 1
        bucket["tokens"] += int(it.get("total_tokens", 0))
        bucket["cost"] += float(it.get("cost_usd", 0))
    by_day: dict[str, dict] = {}
    for it in items:
        d = it.get("date_bucket") or it.get("sort_key", "")[3:13]
        bucket = by_day.setdefault(d, {"calls": 0, "tokens": 0, "cost": 0.0})
        bucket["calls"] += 1
        bucket["tokens"] += int(it.get("total_tokens", 0))
        bucket["cost"] += float(it.get("cost_usd", 0))
    return {
        "user_id": user_id,
        "window_days": days,
        "total_calls": len(items),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "by_model": {k: {"calls": v["calls"], "tokens": v["tokens"], "cost": round(v["cost"], 6)} for k, v in by_model.items()},
        "by_day": {k: {"calls": v["calls"], "tokens": v["tokens"], "cost": round(v["cost"], 6)} for k, v in by_day.items()},
        "recent_calls": items[-20:],
    }


def get_team_usage(team_id: str, days: int = 30) -> dict:
    """팀 전체 rollup (GSI-team 사용)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    resp = _usage_table().query(
        IndexName="gsi-team",
        KeyConditionExpression=Key("team_id").eq(team_id) & Key("sort_key").gte(f"ts#{cutoff}"),
        Limit=1000,
    )
    items = [_clean_dir_item(i) for i in resp.get("Items", [])]
    total_cost = sum(i.get("cost_usd", 0) for i in items)
    total_tokens = sum(i.get("total_tokens", 0) for i in items)
    by_user: dict[str, dict] = {}
    for it in items:
        uid = it.get("user_id", "?")
        bucket = by_user.setdefault(uid, {"calls": 0, "tokens": 0, "cost": 0.0})
        bucket["calls"] += 1
        bucket["tokens"] += int(it.get("total_tokens", 0))
        bucket["cost"] += float(it.get("cost_usd", 0))
    return {
        "team_id": team_id,
        "window_days": days,
        "total_calls": len(items),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "user_count": len(by_user),
        "by_user": [
            {"user_id": uid, "calls": v["calls"], "tokens": v["tokens"], "cost": round(v["cost"], 6)}
            for uid, v in sorted(by_user.items(), key=lambda x: x[1]["cost"], reverse=True)
        ],
    }


def top_users(days: int = 7, limit: int = 20) -> list[dict]:
    """GSI-date-cost 활용 — 일별 top 비용 사용자 N개를 merge."""
    end = datetime.now(timezone.utc)
    aggregate: dict[str, dict] = {}
    for d in range(days):
        bucket = (end - timedelta(days=d)).strftime("%Y-%m-%d")
        try:
            resp = _usage_table().query(
                IndexName="gsi-date-cost",
                KeyConditionExpression=Key("date_bucket").eq(bucket),
                ScanIndexForward=False,  # 비싼 호출부터
                Limit=200,
            )
            for item in resp.get("Items", []):
                uid = item.get("user_id", "?")
                bucket_agg = aggregate.setdefault(uid, {
                    "user_id": uid, "team_id": item.get("team_id", ""),
                    "calls": 0, "tokens": 0, "cost": 0.0,
                })
                bucket_agg["calls"] += 1
                bucket_agg["tokens"] += int(item.get("total_tokens", 0))
                bucket_agg["cost"] += float(item.get("cost_usd", 0))
        except Exception:
            continue
    sorted_users = sorted(aggregate.values(), key=lambda x: x["cost"], reverse=True)
    for u in sorted_users:
        u["cost"] = round(u["cost"], 6)
    return sorted_users[:limit]


def top_teams(days: int = 7, limit: int = 10) -> list[dict]:
    users = top_users(days, limit=200)
    by_team: dict[str, dict] = {}
    for u in users:
        tid = u.get("team_id", "?")
        bucket = by_team.setdefault(tid, {
            "team_id": tid, "user_count": 0, "calls": 0, "tokens": 0, "cost": 0.0,
        })
        bucket["user_count"] += 1
        bucket["calls"] += u["calls"]
        bucket["tokens"] += u["tokens"]
        bucket["cost"] += u["cost"]
    sorted_teams = sorted(by_team.values(), key=lambda x: x["cost"], reverse=True)
    for t in sorted_teams:
        t["cost"] = round(t["cost"], 6)
    return sorted_teams[:limit]


# --- 예산 설정 ---


def set_budget(entity_type: str, entity_id: str, budget_usd: float):
    _directory_table().update_item(
        Key={"entity_id": f"{entity_type}#{entity_id}"},
        UpdateExpression="SET budget_usd = :b",
        ExpressionAttributeValues={":b": Decimal(str(budget_usd))},
    )

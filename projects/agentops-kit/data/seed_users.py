"""
1,000+ 유저 시연용 seed 데이터 생성.

5팀 × 약 25명 사용자 + 30일치 합성 사용 이력.
DynamoDB Directory + Usage 테이블에 일괄 적재.
"""

import os
import sys
import random
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from api.users import (
    upsert_user, upsert_team, _usage_table, _budget_table, _ttl_epoch,
)


TEAMS = [
    {"team_id": "marketing", "name": "Marketing Insights", "budget": 50.0},
    {"team_id": "logistics", "name": "Logistics Operations", "budget": 80.0},
    {"team_id": "data_science", "name": "Data Science", "budget": 200.0},
    {"team_id": "product", "name": "Product Analytics", "budget": 100.0},
    {"team_id": "executive", "name": "Executive Reporting", "budget": 30.0},
]

FIRST = ["Alice", "Bob", "Carol", "David", "Emma", "Frank", "Grace", "Henry",
         "Ivy", "Jack", "Kate", "Liam", "Mia", "Noah", "Olivia", "Paul",
         "Quinn", "Rose", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xavier",
         "Yara", "Zach", "Hyun", "Jisoo", "Minho", "Soyeon"]
LAST = ["Lee", "Kim", "Park", "Choi", "Jung", "Yoon", "Han", "Cho",
        "Smith", "Jones", "Brown", "Davis", "Wilson", "Garcia", "Martinez", "Anderson"]

MODELS = [
    ("global.anthropic.claude-sonnet-4-6", 3.0, 15.0),
    ("global.anthropic.claude-haiku-4-5", 1.0, 5.0),
    ("us.amazon.nova-pro-v1:0", 0.80, 3.20),
]

TOOLS_POOL = [
    "query_sales_data", "analyze_reviews",
    "check_delivery_performance", "get_seller_metrics",
    "text2sql_query", "delegate_to_specialist",
]


def seed_directory(rng):
    print("Seeding teams + users...")
    users = []
    for team in TEAMS:
        n_users = rng.randint(20, 30)
        upsert_team(team["team_id"], team["name"], member_count=n_users, budget_usd=team["budget"])
        for _ in range(n_users):
            first = rng.choice(FIRST)
            last = rng.choice(LAST)
            uid = f"{first.lower()}.{last.lower()}{rng.randint(10,99)}"
            email = f"{uid}@agentops.demo"
            role = "team_admin" if rng.random() < 0.10 else "member"
            user_budget = round(team["budget"] / rng.uniform(10, 30), 2)
            upsert_user(uid, f"{first} {last}", team["team_id"], email, role, user_budget)
            users.append({"user_id": uid, "team_id": team["team_id"]})
    print(f"  total users: {len(users)}")
    return users


def seed_usage(users, rng, days=30):
    print(f"Seeding {days}-day usage history for {len(users)} users...")
    table = _usage_table()
    budget_table = _budget_table()
    now = datetime.now(timezone.utc)
    written = 0
    budget_agg = {}

    for ui, u in enumerate(users):
        r = rng.random()
        if r < 0.80:
            daily_avg = rng.randint(1, 5)
        elif r < 0.95:
            daily_avg = rng.randint(10, 30)
        else:
            daily_avg = rng.randint(50, 150)

        with table.batch_writer() as bw:
            for day in range(days):
                day_date = now - timedelta(days=day)
                n_calls = max(0, int(rng.gauss(daily_avg, daily_avg * 0.4)))

                for _ in range(n_calls):
                    minute = rng.randint(0, 24 * 60 - 1)
                    base = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    ts = base + timedelta(minutes=minute)
                    ts_iso = ts.replace(microsecond=0).isoformat()
                    sort_key = f"ts#{ts_iso}#{uuid.uuid4().hex[:8]}"

                    model_id, in_price, out_price = rng.choices(MODELS, weights=[0.55, 0.35, 0.10])[0]
                    in_tok = rng.randint(500, 5000)
                    out_tok = rng.randint(100, 1500)
                    cost = (in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price

                    n_tools = rng.randint(0, 3)
                    tools = rng.sample(TOOLS_POOL, k=n_tools) if n_tools else ["none"]

                    bw.put_item(Item={
                        "user_id": u["user_id"],
                        "sort_key": sort_key,
                        "team_id": u["team_id"],
                        "ts_epoch_ms": int(ts.timestamp() * 1000),
                        "date_bucket": ts_iso[:10],
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "total_tokens": in_tok + out_tok,
                        "cost_usd": Decimal(str(round(cost, 8))),
                        "cost_usd_sort": Decimal(str(round(cost, 8))),
                        "model": model_id,
                        "tools_used": set(tools),
                        "prompt_version": rng.choice(["v1", "v2"]),
                        "session_id": uuid.uuid4().hex,
                        "trace_id": uuid.uuid4().hex,
                        "latency_ms": rng.randint(800, 8000),
                        "ttl": _ttl_epoch(),
                    })
                    written += 1

                    period = ts_iso[:7]
                    budget_agg[(f"user#{u['user_id']}", period)] = budget_agg.get((f"user#{u['user_id']}", period), 0.0) + cost
                    budget_agg[(f"team#{u['team_id']}", period)] = budget_agg.get((f"team#{u['team_id']}", period), 0.0) + cost

        if (ui + 1) % 20 == 0:
            print(f"  user {ui+1}/{len(users)}: {written} records written so far")

    print(f"Updating BudgetState for {len(budget_agg)} entity-period pairs...")
    for (entity_id, period), used in budget_agg.items():
        budget_table.update_item(
            Key={"entity_id": entity_id, "period": period},
            UpdateExpression="SET used_usd = :v, last_updated = :ts",
            ExpressionAttributeValues={
                ":v": Decimal(str(round(used, 8))),
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    print(f"\nSeeded {written} usage records over {days} days.")


if __name__ == "__main__":
    rng = random.Random(42)
    users = seed_directory(rng)
    seed_usage(users, rng, days=30)
    print("\nDone.")

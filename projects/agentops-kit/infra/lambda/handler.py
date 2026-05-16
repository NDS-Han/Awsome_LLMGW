"""
AgentCore Gateway Lambda 타겟.
단일 Lambda가 5개 도구를 라우팅. Gateway는 MCP를 통해 이 Lambda를 invoke한다.

환경변수 (CloudFormation에서 주입):
    DB_CLUSTER_ARN
    DB_SECRET_ARN
    DB_NAME
    AWS_REGION

Gateway invoke 시 context.client_context.custom["bedrockAgentCoreToolName"]에
MCP 도구 이름이 들어온다. "Target___toolName" 형태이므로 prefix 제거 후 라우팅.
"""

import json
import os
import re
from decimal import Decimal
from typing import Any

import boto3

# --- Aurora Data API 연결 (db.py의 축약 버전 — Lambda 이미지에 별도 import 없이) ---

_rds_client = None


def _client():
    global _rds_client
    if _rds_client is None:
        _rds_client = boto3.client("rds-data", region_name=os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-1"))
    return _rds_client


def _to_params(params: dict | None) -> list[dict]:
    if not params:
        return []
    result = []
    for k, v in params.items():
        if v is None:
            result.append({"name": k, "value": {"isNull": True}})
        elif isinstance(v, bool):
            result.append({"name": k, "value": {"booleanValue": v}})
        elif isinstance(v, int):
            result.append({"name": k, "value": {"longValue": v}})
        elif isinstance(v, float):
            result.append({"name": k, "value": {"doubleValue": v}})
        else:
            result.append({"name": k, "value": {"stringValue": str(v)}})
    return result


def _convert(field: dict) -> Any:
    if field.get("isNull"):
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue"):
        if key in field:
            return field[key]
    return None


def query(sql: str, params: dict | None = None) -> list[dict]:
    resp = _client().execute_statement(
        resourceArn=os.environ["DB_CLUSTER_ARN"],
        secretArn=os.environ["DB_SECRET_ARN"],
        database=os.environ["DB_NAME"],
        sql=sql,
        parameters=_to_params(params),
        includeResultMetadata=True,
    )
    cols = [c["name"] for c in resp.get("columnMetadata", [])]
    return [
        {cols[i]: _convert(f) for i, f in enumerate(record)}
        for record in resp.get("records", [])
    ]


# --- 도구 구현 ---

_STATE_RE = re.compile(r"^[A-Z]{2}$")
_PERIOD_YEAR = re.compile(r"^\d{4}$")
_PERIOD_MONTH = re.compile(r"^\d{4}-\d{2}$")
_PERIOD_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")
_SORT_COLUMNS = {
    "revenue": "total_revenue",
    "orders": "total_orders",
    "review_score": "avg_review_score",
}


def _parse_period(period: str) -> tuple[str, dict]:
    if m := _PERIOD_QUARTER.match(period):
        y, q = int(m.group(1)), int(m.group(2))
        return (
            "EXTRACT(YEAR FROM order_purchase_timestamp)=:year AND EXTRACT(MONTH FROM order_purchase_timestamp) BETWEEN :m1 AND :m2",
            {"year": y, "m1": (q - 1) * 3 + 1, "m2": q * 3},
        )
    if _PERIOD_MONTH.match(period):
        return ("to_char(order_purchase_timestamp,'YYYY-MM')=:ym", {"ym": period})
    if _PERIOD_YEAR.match(period):
        return ("EXTRACT(YEAR FROM order_purchase_timestamp)=:year", {"year": int(period)})
    return ("1=1", {})


def tool_query_sales_data(args: dict) -> dict:
    time_period = args.get("time_period", "")
    category = args.get("category", "all")
    period_where, params = _parse_period(time_period)
    where = f"WHERE order_status='delivered' AND {period_where}"
    if category != "all":
        where += " AND category_english ILIKE :cat_pattern"
        params["cat_pattern"] = f"%{category}%"

    # nosec B608 - WHERE clauses are built from code-internal constants (_parse_period regex output),
    # all user-supplied values flow through :param bindings via _to_params.
    summary = query(f"""
        SELECT ROUND(SUM(price)::numeric,2) AS total_revenue,
               COUNT(DISTINCT order_id) AS order_count,
               ROUND(AVG(price)::numeric,2) AS avg_order_value,
               ROUND(SUM(freight_value)::numeric,2) AS total_freight
        FROM v_order_summary {where}
    """, params)  # nosec B608
    top_cat = query(f"""
        SELECT category_english AS category,
               ROUND(SUM(price)::numeric,2) AS revenue,
               COUNT(DISTINCT order_id) AS orders
        FROM v_order_summary {where} AND category_english IS NOT NULL
        GROUP BY category_english ORDER BY revenue DESC LIMIT 10
    """, params)  # nosec B608
    trend = query(f"""
        SELECT to_char(order_purchase_timestamp,'YYYY-MM') AS month,
               ROUND(SUM(price)::numeric,2) AS revenue,
               COUNT(DISTINCT order_id) AS orders
        FROM v_order_summary {where}
        GROUP BY month ORDER BY month
    """, params)  # nosec B608
    return {
        "time_period": time_period,
        "category_filter": category,
        "summary": summary[0] if summary else {},
        "top_categories": top_cat,
        "monthly_trend": trend,
    }


def tool_analyze_reviews(args: dict) -> dict:
    min_s = max(1, min(int(args.get("min_score", 1)), 5))
    max_s = max(1, min(int(args.get("max_score", 5)), 5))
    limit = max(1, min(int(args.get("limit", 10)), 50))
    category = args.get("category", "all")

    params = {"min_s": min_s, "max_s": max_s, "lim": limit}
    cat_filter = ""
    if category != "all":
        cat_filter = "AND category_english ILIKE :cat_pattern"
        params["cat_pattern"] = f"%{category}%"

    # nosec B608 - cat_filter is a code-internal literal; user category value bound via :cat_pattern.
    score_dist = query(f"""
        SELECT review_score, COUNT(*) AS count,
               ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(),2) AS percentage
        FROM v_order_summary
        WHERE review_score IS NOT NULL AND review_score BETWEEN :min_s AND :max_s {cat_filter}
        GROUP BY review_score ORDER BY review_score
    """, params)  # nosec B608
    sat = query(f"""
        SELECT ROUND(SUM(CASE WHEN review_score>=4 THEN 1 ELSE 0 END)*100.0/COUNT(*),2) AS satisfaction_rate,
               ROUND(AVG(review_score)::numeric,2) AS avg_score,
               COUNT(*) AS total_reviews
        FROM v_order_summary
        WHERE review_score IS NOT NULL AND review_score BETWEEN :min_s AND :max_s {cat_filter}
    """, params)  # nosec B608
    cat_scores = query(f"""
        SELECT category_english AS category,
               ROUND(AVG(review_score)::numeric,2) AS avg_score,
               COUNT(*) AS review_count
        FROM v_order_summary
        WHERE review_score IS NOT NULL AND category_english IS NOT NULL
          AND review_score BETWEEN :min_s AND :max_s {cat_filter}
        GROUP BY category_english HAVING COUNT(*)>=10
        ORDER BY avg_score DESC LIMIT 10
    """, params)  # nosec B608
    samples = query(f"""
        SELECT review_score, review_comment_title,
               LEFT(review_comment_message,200) AS review_comment,
               COALESCE(category_english,'unknown') AS category
        FROM v_order_summary
        WHERE review_score BETWEEN :min_s AND :max_s
          AND review_comment_message IS NOT NULL
          AND LENGTH(review_comment_message)>10 {cat_filter}
        ORDER BY RANDOM() LIMIT :lim
    """, params)  # nosec B608
    return {
        "filters": {"min_score": min_s, "max_score": max_s, "category": category},
        "satisfaction": sat[0] if sat else {},
        "score_distribution": score_dist,
        "top_category_scores": cat_scores,
        "sample_reviews": samples,
    }


def tool_check_delivery_performance(args: dict) -> dict:
    state = (args.get("state") or "all").upper()
    threshold = max(1, min(int(args.get("threshold_days", 14)), 60))

    params = {"threshold": threshold}
    state_filter = ""
    if state != "ALL":
        if not _STATE_RE.match(state):
            return {"error": "invalid_state", "message": "State must be 2 uppercase letters or 'all'"}
        state_filter = "AND c.customer_state=:state"
        params["state"] = state

    # nosec B608 - state_filter / bf are code-internal literals; state value (regex-validated) bound via :state.
    overall = query(f"""
        SELECT COUNT(*) AS total_deliveries,
               ROUND(AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date-o.order_purchase_timestamp))/86400.0)::numeric,1) AS avg_delivery_days,
               ROUND(SUM(CASE WHEN o.order_delivered_customer_date<=o.order_estimated_delivery_date THEN 1 ELSE 0 END)::numeric*100/COUNT(*),2) AS on_time_rate,
               ROUND(SUM(CASE WHEN EXTRACT(EPOCH FROM (o.order_delivered_customer_date-o.order_purchase_timestamp))/86400.0>:threshold THEN 1 ELSE 0 END)::numeric*100/COUNT(*),2) AS late_rate_by_threshold
        FROM orders o JOIN customers c ON o.customer_id=c.customer_id
        WHERE o.order_status='delivered'
          AND o.order_delivered_customer_date IS NOT NULL
          AND o.order_estimated_delivery_date IS NOT NULL {state_filter}
    """, params)  # nosec B608
    bf = "WHERE customer_state=:state" if "state" in params else ""
    breakdown = query(f"""
        SELECT customer_state AS state, total_deliveries, on_time_rate,
               ROUND(avg_delivery_days::numeric,1) AS avg_delivery_days,
               ROUND(avg_delay_days::numeric,1) AS avg_delay_days
        FROM v_delivery_performance {bf}
        ORDER BY total_deliveries DESC LIMIT 15
    """, {k: v for k, v in params.items() if k == "state"})  # nosec B608
    return {
        "filters": {"state": state.lower() if state == "ALL" else state, "threshold_days": threshold},
        "overall_metrics": overall[0] if overall else {},
        "state_breakdown": breakdown,
    }


def tool_get_seller_metrics(args: dict) -> dict:
    top_n = max(1, min(int(args.get("top_n", 10)), 50))
    sort_by = args.get("sort_by", "revenue")
    sort_col = _SORT_COLUMNS.get(sort_by, "total_revenue")

    overall = query("""
        SELECT COUNT(DISTINCT seller_id) AS total_sellers,
               ROUND(AVG(total_revenue)::numeric,2) AS avg_revenue_per_seller,
               ROUND(AVG(total_orders)::numeric,1) AS avg_orders_per_seller,
               ROUND(AVG(avg_review_score)::numeric,2) AS avg_review_score,
               ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_revenue)::numeric,2) AS median_revenue
        FROM v_seller_performance
    """)
    # nosec B608 - sort_col is constrained to _SORT_COLUMNS whitelist values, top_n bound via :top_n.
    top = query(f"""
        SELECT seller_id, seller_city, seller_state, total_orders,
               ROUND(total_revenue::numeric,2) AS total_revenue,
               ROUND(avg_review_score::numeric,2) AS avg_review_score,
               product_count,
               ROUND(avg_delivery_delay_days::numeric,1) AS avg_delivery_delay_days
        FROM v_seller_performance
        WHERE {sort_col} IS NOT NULL
        ORDER BY {sort_col} DESC LIMIT :top_n
    """, {"top_n": top_n})  # nosec B608
    state_dist = query("""
        SELECT seller_state AS state, COUNT(*) AS seller_count,
               ROUND(SUM(total_revenue)::numeric,2) AS total_revenue,
               ROUND(AVG(avg_review_score)::numeric,2) AS avg_review_score
        FROM v_seller_performance
        GROUP BY seller_state ORDER BY total_revenue DESC LIMIT 10
    """)
    return {
        "sort_by": sort_by,
        "overall_stats": overall[0] if overall else {},
        "top_sellers": top,
        "state_distribution": state_dist,
    }


# --- Text2SQL (Gateway 안에서도 동작) ---

SCHEMA_INFO = """
Tables: orders, order_items, order_reviews, products, sellers, customers,
order_payments, geolocation, category_translation.
Views: v_order_summary, v_monthly_revenue, v_seller_performance,
v_delivery_performance, v_category_revenue.
"""

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|CALL|EXECUTE|MERGE|VACUUM|ANALYZE|LOCK)\b",
    re.IGNORECASE,
)
FORBIDDEN_SCHEMAS = re.compile(
    r"\b(pg_catalog|information_schema|pg_shadow|pg_user|pg_roles|pg_authid)\b",
    re.IGNORECASE,
)
SQL_COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)


def _validate_sql(sql: str) -> tuple[bool, str]:
    clean = SQL_COMMENT.sub(" ", sql).strip()
    if not clean:
        return False, "Empty SQL"
    if not clean.upper().startswith(("SELECT", "WITH")):
        return False, "Only SELECT/WITH allowed"
    if FORBIDDEN_KEYWORDS.search(clean):
        return False, "Forbidden keyword"
    if FORBIDDEN_SCHEMAS.search(clean):
        return False, "System catalog not allowed"
    if clean.rstrip(";").count(";") > 0:
        return False, "Multiple statements not allowed"
    if SQL_COMMENT.search(sql):
        return False, "SQL comments not allowed"
    return True, ""


def _enforce_limit(sql: str, max_rows: int) -> str:
    stripped = sql.rstrip("; \n\t")
    if re.search(r"\bLIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*$", stripped, re.IGNORECASE):
        return re.sub(r"\bLIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*$", f"LIMIT {max_rows}", stripped, flags=re.IGNORECASE)
    return f"{stripped} LIMIT {max_rows}"


def tool_text2sql_query(args: dict) -> dict:
    question = args.get("question", "")
    max_rows = min(max(int(args.get("max_rows", 20)), 1), 100)
    if len(question) > 2000:
        return {"error": "question_too_long"}

    # Bedrock으로 SQL 생성
    bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-1"))
    model_id = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    prompt = f"""You are a PostgreSQL expert. Convert the user's question into a single read-only SELECT query.

{SCHEMA_INFO}

Rules:
1. Return ONLY the SQL query, no markdown, no explanation.
2. Always add LIMIT unless aggregating to a single row.
3. Do NOT use DDL/DML, pg_catalog, information_schema, or SQL comments.
4. Return exactly ONE statement.
5. If the user request cannot be fulfilled safely, return: SELECT 'cannot_fulfill_safely' AS reason

<user_question>
{question}
</user_question>

SQL:"""
    resp = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    sql = json.loads(resp["body"].read())["content"][0]["text"].strip()
    sql = re.sub(r"^```(?:sql)?\s*", "", sql)
    sql = re.sub(r"\s*```$", "", sql).strip()

    valid, reason = _validate_sql(sql)
    if not valid:
        return {"error": "sql_validation_failed", "reason": reason, "generated_sql": sql}

    sql = _enforce_limit(sql, max_rows)
    rows = query(sql)
    return {
        "question": question,
        "generated_sql": sql,
        "row_count": len(rows),
        "rows": rows[:max_rows],
    }


# --- Dispatcher ---

def tool_delegate_to_specialist(args: dict) -> dict:
    """Agent Gateway: specialist 에이전트에게 질의를 위임 (A2A).

    args: {"specialist": "reviews"|"logistics", "query": str}
    """
    specialist = args.get("specialist", "").lower()
    query = args.get("query", "")

    specialist_arns = {
        "reviews": os.environ.get("REVIEWS_SPECIALIST_ARN"),
        "logistics": os.environ.get("LOGISTICS_SPECIALIST_ARN"),
    }
    arn = specialist_arns.get(specialist)
    if not arn:
        return {
            "error": "unknown_specialist",
            "available": [k for k, v in specialist_arns.items() if v],
        }

    client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-1"))
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        qualifier="DEFAULT",
        payload=json.dumps({"prompt": query}).encode("utf-8"),
    )
    body = resp.get("response")
    raw = body.read() if hasattr(body, "read") else b"".join(body)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = {"response": raw.decode("utf-8", errors="replace")}

    return {
        "specialist": specialist,
        "query": query,
        "specialist_response": data.get("response", ""),
        "specialist_tools_used": data.get("tools_used", []),
    }


TOOLS = {
    "query_sales_data": tool_query_sales_data,
    "analyze_reviews": tool_analyze_reviews,
    "check_delivery_performance": tool_check_delivery_performance,
    "get_seller_metrics": tool_get_seller_metrics,
    "text2sql_query": tool_text2sql_query,
    "delegate_to_specialist": tool_delegate_to_specialist,
}


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def lambda_handler(event, context):
    """
    AgentCore Gateway → Lambda 호출 시:
    - event: 도구 호출 arguments (JSON 객체)
    - context.client_context.custom.bedrockAgentCoreToolName: 'Target___toolName' 형식

    toolName prefix 제거 후 라우팅.
    """
    # Gateway가 주는 tool name (prefix 제거)
    tool_name = None
    try:
        raw = context.client_context.custom.get("bedrockAgentCoreToolName")
        if raw and "___" in raw:
            tool_name = raw.split("___", 1)[1]
        else:
            tool_name = raw
    except Exception:
        pass

    # 수동 테스트: event에 tool 키가 있으면 그걸 사용
    if not tool_name:
        tool_name = event.get("tool")
        event = event.get("args", event)

    handler = TOOLS.get(tool_name)
    if not handler:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "unknown_tool", "tool": tool_name}),
        }

    try:
        result = handler(event or {})
        return {
            "statusCode": 200,
            "body": json.dumps(result, default=_json_default),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "tool_execution_failed", "message": str(e)[:500]}),
        }

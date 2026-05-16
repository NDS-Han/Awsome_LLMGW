"""
AgentCore Gateway 생성 + 도구 라우터 Lambda 등록.

Usage:
    python infra/setup_gateway.py               # 생성 (1회)
    python infra/setup_gateway.py --update      # Lambda 타겟만 재등록
    python infra/setup_gateway.py --delete      # 게이트웨이 삭제
"""

import os
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient

GATEWAY_NAME = "agentops-ecommerce-gateway"
TARGET_NAME = "EcommerceAnalyticsTools"

# MCP 도구 스키마 (Gateway가 LLM에 노출하는 도구 정의)
TOOL_SCHEMAS = [
    {
        "name": "query_sales_data",
        "description": "Query e-commerce sales data: revenue, order volume, top categories, monthly trend.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "time_period": {
                    "type": "string",
                    "description": "Time period. 'YYYY' / 'YYYY-MM' / 'YYYY-QN' (e.g., '2017-Q4')"
                },
                "category": {
                    "type": "string",
                    "description": "Product category filter. 'all' for all categories."
                },
            },
            "required": ["time_period"],
        },
    },
    {
        "name": "analyze_reviews",
        "description": "Analyze customer reviews: score distribution, satisfaction, category scores, sample reviews.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_score": {"type": "integer", "description": "Min review score (1-5)"},
                "max_score": {"type": "integer", "description": "Max review score (1-5)"},
                "category": {"type": "string", "description": "Category filter"},
                "limit": {"type": "integer", "description": "Number of sample reviews (1-50)"},
            },
        },
    },
    {
        "name": "check_delivery_performance",
        "description": "Check delivery performance: on-time rate, state breakdown, late delivery analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Brazilian state code (2 uppercase letters) or 'all'"},
                "threshold_days": {"type": "integer", "description": "Max acceptable delivery days (1-60)"},
            },
        },
    },
    {
        "name": "get_seller_metrics",
        "description": "Top seller performance metrics ranked by revenue, orders, or review score.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "top_n": {"type": "integer", "description": "Number of top sellers (1-50)"},
                "sort_by": {"type": "string", "description": "'revenue', 'orders', or 'review_score'"},
            },
        },
    },
    {
        "name": "text2sql_query",
        "description": "Convert a natural-language analytical question into SQL and run it against the e-commerce DB.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural-language question"},
                "max_rows": {"type": "integer", "description": "Max rows to return (1-100)"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "delegate_to_specialist",
        "description": (
            "Delegate a focused question to a specialist agent (Agent Gateway / A2A). "
            "Use this when the question is deeply specialized: "
            "'reviews' for customer satisfaction/sentiment analysis, "
            "'logistics' for delivery/seller performance analysis."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "specialist": {
                    "type": "string",
                    "description": "'reviews' or 'logistics'",
                },
                "query": {"type": "string", "description": "Focused question for the specialist"},
            },
            "required": ["specialist", "query"],
        },
    },
]


def create():
    region = os.environ.get("AWS_REGION", "us-east-1")
    lambda_arn = os.environ["TOOL_ROUTER_LAMBDA_ARN"]

    client = GatewayClient(region_name=region)
    import logging
    client.logger.setLevel(logging.INFO)

    print(f"Creating OAuth authorizer (Cognito)...")
    cognito = client.create_oauth_authorizer_with_cognito(GATEWAY_NAME)

    print(f"Creating Gateway '{GATEWAY_NAME}'...")
    gateway = client.create_mcp_gateway(
        name=GATEWAY_NAME,
        role_arn=None,  # 자동 생성
        authorizer_config=cognito["authorizer_config"],
        enable_semantic_search=True,
    )
    print(f"Gateway created: {gateway['gatewayUrl']}")

    import time
    print("Waiting 30s for IAM propagation...")
    time.sleep(30)

    print(f"Registering Lambda target with {len(TOOL_SCHEMAS)} tools...")
    client.create_mcp_gateway_target(
        gateway=gateway,
        name=TARGET_NAME,
        target_type="lambda",
        target_payload={
            "lambdaArn": lambda_arn,
            "toolSchema": {"inlinePayload": TOOL_SCHEMAS},
        },
    )

    # .env 에 Gateway 정보 append
    env_path = Path(__file__).resolve().parent.parent / ".env"
    existing = env_path.read_text() if env_path.exists() else ""
    gateway_lines = {
        "GATEWAY_URL": gateway["gatewayUrl"],
        "GATEWAY_ID": gateway["gatewayId"],
        "COGNITO_CLIENT_ID": cognito["client_info"]["client_id"],
        "COGNITO_CLIENT_SECRET": cognito["client_info"]["client_secret"],
        "COGNITO_TOKEN_ENDPOINT": cognito["client_info"]["token_endpoint"],
        "COGNITO_SCOPE": cognito["client_info"]["scope"],
    }
    # 기존 gateway 관련 키 제거
    lines = [ln for ln in existing.splitlines() if not any(ln.startswith(k + "=") for k in gateway_lines)]
    lines.append("")
    lines.append("# Added by setup_gateway.py")
    for k, v in gateway_lines.items():
        lines.append(f"{k}={v}")
    env_path.write_text("\n".join(lines) + "\n")
    print(f"\nGateway info appended to {env_path}")
    print("\nGateway URL:", gateway["gatewayUrl"])


def update_target_tools():
    """기존 Gateway 타겟에 최신 toolSchema 반영 (에이전트 재배포 없이)."""
    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    lambda_arn = os.environ["TOOL_ROUTER_LAMBDA_ARN"]
    cp = boto3.client("bedrock-agentcore-control", region_name=region)

    gateways = cp.list_gateways().get("items", [])
    gw = next((g for g in gateways if g["name"] == GATEWAY_NAME), None)
    if not gw:
        raise RuntimeError(f"Gateway {GATEWAY_NAME!r} not found — create first.")
    gid = gw["gatewayId"]
    targets = cp.list_gateway_targets(gatewayIdentifier=gid).get("items", [])
    target = next((t for t in targets if t["name"] == TARGET_NAME), None)
    if not target:
        raise RuntimeError(f"Target {TARGET_NAME!r} not found.")

    cp.update_gateway_target(
        gatewayIdentifier=gid,
        targetId=target["targetId"],
        name=TARGET_NAME,
        targetConfiguration={
            "mcp": {
                "lambda": {
                    "lambdaArn": lambda_arn,
                    "toolSchema": {"inlinePayload": TOOL_SCHEMAS},
                }
            }
        },
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
    )
    print(f"Updated {len(TOOL_SCHEMAS)} tools on target {TARGET_NAME}")


def delete_gateway():
    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    cp = boto3.client("bedrock-agentcore-control", region_name=region)

    # 이름으로 gateway 찾기
    gateways = cp.list_gateways().get("items", [])
    for g in gateways:
        if g["name"] == GATEWAY_NAME:
            gid = g["gatewayId"]
            print(f"Deleting targets of {gid}...")
            for t in cp.list_gateway_targets(gatewayIdentifier=gid).get("items", []):
                cp.delete_gateway_target(gatewayIdentifier=gid, targetId=t["targetId"])
            print(f"Deleting gateway {gid}...")
            cp.delete_gateway(gatewayIdentifier=gid)
            print("Deleted.")
            return
    print(f"No gateway named {GATEWAY_NAME!r} found.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--update-tools", action="store_true")
    args = parser.parse_args()
    if args.delete:
        delete_gateway()
    elif args.update_tools:
        update_target_tools()
    else:
        create()

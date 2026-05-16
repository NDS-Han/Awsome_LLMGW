"""
AgentCore Registry 생성 + 우리 에이전트/Gateway를 레코드로 등록.

Usage:
    python infra/setup_registry.py               # 생성 + 4개 레코드 등록
    python infra/setup_registry.py --delete      # 레지스트리 삭제
"""

import os
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import boto3

REGISTRY_NAME = "agentops_ecommerce_registry"
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _client():
    return boto3.client("bedrock-agentcore-control", region_name=REGION)


def _registry_id_from_arn(arn: str) -> str:
    return arn.rstrip("/").split("/")[-1]


def _find_registry(name: str) -> dict | None:
    """name 일치하고 status=READY 인 레지스트리 반환."""
    c = _client()
    token = None
    while True:
        kwargs = {"maxResults": 50}
        if token:
            kwargs["nextToken"] = token
        resp = c.list_registries(**kwargs)
        for r in resp.get("registries", []):
            if r.get("name") == name and r.get("status") == "READY":
                return r
        token = resp.get("nextToken")
        if not token:
            return None


def create_registry() -> dict:
    c = _client()
    existing = _find_registry(REGISTRY_NAME)
    if existing:
        print(f"Registry {REGISTRY_NAME!r} already exists: {existing['registryId']}")
        return existing

    print(f"Creating registry {REGISTRY_NAME!r}...")
    resp = c.create_registry(
        name=REGISTRY_NAME,
        description="AgentOps Kit — AWS Summit 2026 demo registry. Catalogs agents, MCP servers, and tools for the e-commerce analytics workload.",
        authorizerType="AWS_IAM",
        approvalConfiguration={"autoApproval": True},
    )
    arn = resp["registryArn"]
    reg_id = _registry_id_from_arn(arn)
    print(f"Registry created: {reg_id} ({arn})")
    return {"registryId": reg_id, "registryArn": arn, "name": REGISTRY_NAME}


def register_runtime_agent(reg_id: str, name: str, description: str, arn: str, role: str):
    """AgentCore Runtime을 A2A 레코드로 등록 (A2A Agent Card 표준 스펙)."""
    c = _client()
    # A2A Agent Card (Google A2A protocol v0.2)
    agent_card = {
        "protocolVersion": "0.2.0",
        "name": name,
        "description": description,
        "url": arn,
        "version": "1.0.0",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": f"{role}_analytics",
                "name": f"{role.title()} analytics",
                "description": description,
                "tags": [role, "ecommerce", "analytics"],
            }
        ],
    }
    try:
        print(f"Registering A2A record: {name}...")
        c.create_registry_record(
            registryId=reg_id,
            name=name,
            description=description,
            descriptorType="A2A",
            descriptors={
                "a2a": {
                    "agentCard": {
                        "inlineContent": json.dumps(agent_card),
                    }
                }
            },
        )
        print(f"  registered: {name}")
    except c.exceptions.ConflictException:
        print(f"  already exists: {name} (skipped)")


def register_mcp_server(reg_id: str, name: str, description: str, gateway_url: str, tools: list[dict]):
    """Gateway를 CUSTOM 타입 레코드로 등록 (MCP 메타데이터 포함).

    (MCP descriptor 스키마 validation이 엄격하여 CUSTOM 타입으로 우회.
    프로덕션 배포 시 MCP initialize 응답을 그대로 넣으면 auto-detect 가능.)
    """
    c = _client()

    custom_content = {
        "kind": "mcp_server",
        "protocolVersion": "2025-06-18",
        "server": {
            "name": name,
            "title": name.replace("_", " ").title(),
            "description": description,
            "url": gateway_url,
            "transport": "streamable-http",
            "authorization": {"type": "oauth2", "provider": "cognito"},
        },
        "capabilities": {"tools": {"listChanged": False}},
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", ""),
            }
            for t in tools
        ],
    }

    try:
        print(f"Registering CUSTOM (MCP) record: {name}...")
        c.create_registry_record(
            registryId=reg_id,
            name=name,
            description=description,
            descriptorType="CUSTOM",
            descriptors={
                "custom": {"inlineContent": json.dumps(custom_content)},
            },
        )
        print(f"  registered: {name}")
    except c.exceptions.ConflictException:
        print(f"  already exists: {name} (skipped)")


def _load_specialist_arns() -> dict:
    import yaml
    with open(Path(__file__).resolve().parent.parent / ".bedrock_agentcore.yaml") as f:
        conf = yaml.safe_load(f)
    out = {}
    for name, cfg in conf["agents"].items():
        out[name] = cfg["bedrock_agentcore"]["agent_arn"]
    return out


def _load_gateway_tools() -> list[dict]:
    """Gateway에 등록된 도구 스키마를 가져옴."""
    gateway_name = "agentops-ecommerce-gateway"
    cp = _client()
    gateways = cp.list_gateways().get("items", [])
    gw = next((g for g in gateways if g["name"] == gateway_name), None)
    if not gw:
        return []
    targets = cp.list_gateway_targets(gatewayIdentifier=gw["gatewayId"]).get("items", [])
    if not targets:
        return []
    target_detail = cp.get_gateway_target(
        gatewayIdentifier=gw["gatewayId"], targetId=targets[0]["targetId"]
    )
    schema = (
        target_detail.get("targetConfiguration", {})
        .get("mcp", {})
        .get("lambda", {})
        .get("toolSchema", {})
        .get("inlinePayload", [])
    )
    return [{"name": t["name"], "description": t.get("description", "")} for t in schema]


def setup():
    reg = create_registry()
    reg_id = reg["registryId"]

    # 1. Runtime 에이전트 3개 등록 (A2A)
    arns = _load_specialist_arns()
    agents = [
        ("ecommerce_analytics_main", "Main orchestrator agent — routes queries to specialists and directly handles analytical questions.", arns.get("ecommerce_analytics"), "main"),
        ("reviews_specialist", "Specialist agent for customer review / sentiment / satisfaction analysis.", arns.get("reviews_specialist"), "specialist"),
        ("logistics_specialist", "Specialist agent for delivery performance / seller metrics / shipping analysis.", arns.get("logistics_specialist"), "specialist"),
    ]
    for name, desc, arn, role in agents:
        if arn:
            register_runtime_agent(reg_id, name, desc, arn, role)

    # 2. MCP 서버 등록 (Gateway)
    gateway_url = os.environ.get("GATEWAY_URL")
    if gateway_url:
        tools = _load_gateway_tools()
        register_mcp_server(
            reg_id,
            "ecommerce_analytics_mcp_gateway",
            "AgentCore Gateway exposing 6 analytical tools (sales, reviews, delivery, sellers, text2sql, delegate_to_specialist) over MCP.",
            gateway_url,
            tools,
        )

    # 3. Registry ID를 .env에 append
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        content = env_path.read_text()
        if "REGISTRY_ID" not in content:
            env_path.write_text(content.rstrip() + f"\n\n# Agent Registry\nREGISTRY_ID={reg_id}\nREGISTRY_NAME={REGISTRY_NAME}\n")
            print(f".env updated with REGISTRY_ID={reg_id}")

    print("\nAll records submitted. Check status with: aws bedrock-agentcore-control list-registry-records --registry-id", reg_id)


def delete_registry():
    c = _client()
    reg = _find_registry(REGISTRY_NAME)
    if not reg:
        print(f"No registry {REGISTRY_NAME!r} found.")
        return
    reg_id = reg["registryId"]
    # 레코드 먼저 삭제
    token = None
    while True:
        kwargs = {"registryId": reg_id, "maxResults": 50}
        if token:
            kwargs["nextToken"] = token
        resp = c.list_registry_records(**kwargs)
        for rec in resp.get("items", []):
            print(f"  deleting record: {rec['name']}")
            c.delete_registry_record(registryId=reg_id, recordId=rec["recordId"])
        token = resp.get("nextToken")
        if not token:
            break
    c.delete_registry(registryId=reg_id)
    print(f"Deleted registry {reg_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    if args.delete:
        delete_registry()
    else:
        setup()

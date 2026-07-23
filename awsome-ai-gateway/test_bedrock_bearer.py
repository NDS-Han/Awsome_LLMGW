#!/usr/bin/env python3
"""Test Bedrock call through gateway-proxy using the bearer token set in .env.

This script uses the virtual key issued by /internal/test/issue-key and calls
the local gateway's OpenAI-compatible /v1/chat/completions endpoint with a
Bedrock model alias. The gateway routes the request to BedrockAdapter, which
uses the AWS_BEARER_TOKEN_BEDROCK env var to authenticate to Bedrock.
"""

import json
import sys
from pathlib import Path

import requests

ENV_FILE = Path(__file__).with_name("test_user_env.json")
MODEL = "claude-haiku-4-5-20251001"  # Bedrock alias seeded in model_aliases


def main() -> None:
    if not ENV_FILE.exists():
        print(f"{ENV_FILE.name} not found. Create it first via /internal/test/issue-key.")
        sys.exit(1)

    with ENV_FILE.open() as f:
        env = json.load(f)

    vk = env.get("virtual_key")
    endpoint = env.get("gateway_endpoint", "http://localhost:8000")
    if not vk:
        print("virtual_key missing in test_user_env.json")
        sys.exit(1)

    url = f"{endpoint.rstrip('/')}/model/{MODEL}/converse"
    headers = {
        "Authorization": f"Bearer {vk}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": "Hello, say a short hello."}],
            }
        ],
        "inferenceConfig": {"maxTokens": 64},
    }

    print(f"POST {url}")
    print(f"model: {MODEL}")
    print(f"Authorization: Bearer {vk[:16]}...")

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.exceptions.ConnectionError as e:
        print(f"Connection failed: {e}\nIs gateway-proxy running on {endpoint}?")
        sys.exit(1)

    print(f"\nstatus: {resp.status_code}")
    print("headers:", dict(resp.headers))
    print("body (first 2000 chars):")
    print(resp.text[:2000])

    if resp.status_code == 200:
        try:
            data = resp.json()
            content = data["output"]["message"]["content"][0]["text"]
            print(f"\nassistant: {content}")
        except Exception:
            pass


if __name__ == "__main__":
    main()

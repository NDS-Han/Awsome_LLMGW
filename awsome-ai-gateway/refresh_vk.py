#!/usr/bin/env python3
"""Refresh (re-issue) the Virtual Key for a DB user by running KeyService inside admin-api.

Similar to test_bedrock_bearer.py, this is a single runnable file. It calls
admin-api's KeyService.issue_key directly, then updates ~/.gateway-vk and
test_user_env.json.

Usage:
    python refresh_vk.py
    python refresh_vk.py --user-id <uuid>
    python refresh_vk.py --env-file path/to/test_user_env.json
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / "test_user_env.json"
VK_FILE = Path.home() / ".gateway-vk"

# Runs inside the admin-api container.
ISSUE_SCRIPT = r"""
import asyncio, json, os, uuid
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.encryption import AESEncryptionService
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.auth import CurrentUser
from app.core.redis_client import create_redis_client
from app.repositories.user_repository import UserRepository
from app.services.key_service import KeyService

async def main():
    settings = get_settings()
    user_id = uuid.UUID(os.environ["USER_ID"])
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_user(user_id)
        if user is None:
            print("__USER_NOT_FOUND__", flush=True)
            return
        redis = await create_redis_client()
        encryption = AESEncryptionService(settings.VIRTUAL_KEY_ENCRYPTION_KEY.get_secret_value())
        cache_mgr = CacheInvalidationManager(redis)
        key_service = KeyService(encryption, cache_mgr)
        actor = CurrentUser(user_id=user.id, email=user.email, role=user.role, team_id=user.team_id)
        result = await key_service.issue_key(session, user_id=user.id, actor=actor, user=user)
        await session.commit()
        print(json.dumps({
            "virtual_key": result.virtual_key,
            "expires_at": result.expires_at.isoformat(),
            "key_id": result.key_id,
        }), flush=True)

asyncio.run(main())
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue/refresh a Virtual Key for a DB user")
    parser.add_argument(
        "--user-id",
        help="UUID of the user to issue a VK for (default: user_id from test_user_env.json)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help="Path to test_user_env.json to update",
    )
    parser.add_argument(
        "--vk-file",
        type=Path,
        default=VK_FILE,
        help="Path to write the VK to",
    )
    args = parser.parse_args()

    user_id = args.user_id
    if not user_id and args.env_file.exists():
        env = json.loads(args.env_file.read_text())
        user_id = env.get("user_id")
    if not user_id:
        print("user_id is required (pass --user-id or have it in test_user_env.json)")
        sys.exit(1)

    cmd = [
        "docker", "compose", "exec",
        "-T",
        "-e", f"USER_ID={user_id}",
        "admin-api", "python", "-",
    ]

    print(f"[refresh_vk] issuing VK for user {user_id} via admin-api container ...")
    result = subprocess.run(
        cmd,
        input=ISSUE_SCRIPT,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )

    if result.returncode != 0:
        print("[refresh_vk] failed:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    # The container prints JSON, possibly mixed with log/structlog lines.
    payload = None
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and "virtual_key" in payload:
                break
        except json.JSONDecodeError:
            continue
    else:
        print("[refresh_vk] could not find VK JSON in output:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    if payload.get("virtual_key") == "__USER_NOT_FOUND__":
        print(f"[refresh_vk] user {user_id} not found in DB")
        sys.exit(1)

    vk = payload["virtual_key"]
    expires_at = payload.get("expires_at", datetime.now(timezone.utc).isoformat())
    key_id = payload.get("key_id")

    # Write ~/.gateway-vk
    args.vk_file.write_text(vk)
    args.vk_file.chmod(0o600)
    print(f"[refresh_vk] wrote {args.vk_file} ({len(vk)} chars, expires {expires_at})")

    # Update test_user_env.json
    if args.env_file.exists():
        env = json.loads(args.env_file.read_text())
        env["virtual_key"] = vk
        env["expires_at"] = expires_at
        if key_id:
            env["key_id"] = key_id
        args.env_file.write_text(json.dumps(env, indent=2) + "\n")
        print(f"[refresh_vk] updated {args.env_file}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create a new user directly in the admin-api DB, without SSO.

Similar to refresh_vk.py, this runs KeyService/UserRepository inside the
admin-api container. After creation it can update test_user_env.json so you
can immediately run refresh_vk.py to issue a VK.

Usage:
    python create_user.py --email alice@example.com --display-name Alice
    python create_user.py --email bob@example.com --role DEVELOPER --team-id <uuid>
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / "test_user_env.json"

# Runs inside the admin-api container.
CREATE_SCRIPT = r"""
import asyncio, json, os, uuid
from datetime import datetime, timezone
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.auth import User, UserRole
from app.repositories.user_repository import UserRepository

async def main():
    settings = get_settings()
    user = User(
        id=uuid.UUID(os.environ["USER_ID"]) if os.environ.get("USER_ID") else uuid.uuid4(),
        email=os.environ["EMAIL"],
        display_name=os.environ["DISPLAY_NAME"],
        role=UserRole(os.environ.get("ROLE", "DEVELOPER")),
        sso_subject=os.environ.get("SSO_SUBJECT") or os.environ["EMAIL"],
        provider=os.environ.get("PROVIDER", "sts"),
        is_active=os.environ.get("IS_ACTIVE", "true").lower() == "true",
        team_id=uuid.UUID(os.environ["TEAM_ID"]) if os.environ.get("TEAM_ID") else None,
    )
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(user.email)
        if existing:
            print(json.dumps({
                "error": "USER_EXISTS",
                "user_id": str(existing.id),
                "email": existing.email,
            }), flush=True)
            return
        created = await repo.create_user(user)
        await session.commit()
        print(json.dumps({
            "user_id": str(created.id),
            "email": created.email,
            "display_name": created.display_name,
            "role": created.role.value,
            "team_id": str(created.team_id) if created.team_id else None,
            "sso_subject": created.sso_subject,
            "provider": created.provider,
            "is_active": created.is_active,
            "created_at": created.created_at.isoformat() if created.created_at else datetime.now(timezone.utc).isoformat(),
        }), flush=True)

asyncio.run(main())
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a user directly in the admin-api DB")
    parser.add_argument("--email", required=True, help="User email (unique)")
    parser.add_argument("--display-name", required=True, help="Display name")
    parser.add_argument("--role", default="DEVELOPER", choices=["ADMIN", "TEAM_LEADER", "DEVELOPER"], help="User role")
    parser.add_argument("--team-id", help="Optional team UUID")
    parser.add_argument("--sso-subject", help="Optional SSO subject (default: email)")
    parser.add_argument("--provider", default="sts", help="Auth provider (default: sts)")
    parser.add_argument("--user-id", help="Optional fixed UUID (random if omitted)")
    parser.add_argument("--inactive", action="store_true", help="Create as inactive")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help="Path to test_user_env.json to create/update",
    )
    parser.add_argument(
        "--update-env",
        action="store_true",
        default=True,
        help="Update test_user_env.json with the new user (default: True)",
    )
    parser.add_argument(
        "--no-update-env",
        action="store_true",
        dest="update_env",
        help="Do not update test_user_env.json",
    )
    args = parser.parse_args()

    env = {}
    if args.env_file.exists():
        env = json.loads(args.env_file.read_text())

    team_id = args.team_id or env.get("team_id")

    cmd = [
        "docker", "compose", "exec",
        "-T",
        "-e", f"EMAIL={args.email}",
        "-e", f"DISPLAY_NAME={args.display_name}",
        "-e", f"ROLE={args.role}",
        "-e", f"PROVIDER={args.provider}",
        "-e", f"IS_ACTIVE={str(not args.inactive).lower()}",
    ]
    if args.user_id:
        cmd += ["-e", f"USER_ID={args.user_id}"]
    if team_id:
        cmd += ["-e", f"TEAM_ID={team_id}"]
    if args.sso_subject:
        cmd += ["-e", f"SSO_SUBJECT={args.sso_subject}"]
    cmd += ["admin-api", "python", "-"]

    print(f"[create_user] creating user {args.email} via admin-api container ...")
    result = subprocess.run(
        cmd,
        input=CREATE_SCRIPT,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )

    if result.returncode != 0:
        print("[create_user] failed:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    payload = None
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                break
        except json.JSONDecodeError:
            continue
    else:
        print("[create_user] could not find JSON in output:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    if payload.get("error") == "USER_EXISTS":
        print(f"[create_user] user already exists: {payload['email']} ({payload['user_id']})")
        sys.exit(2)

    print(f"[create_user] created user {payload['user_id']} ({payload['email']}, role={payload['role']})")

    if args.update_env:
        env.update({
            "user_id": payload["user_id"],
            "email": payload["email"],
            "team_id": payload["team_id"] or env.get("team_id", ""),
            "gateway_endpoint": env.get("gateway_endpoint", "http://localhost:8000"),
        })
        # Remove stale VK fields because the new user does not have a VK yet.
        for key in ("virtual_key", "key_id", "expires_at"):
            env.pop(key, None)
        args.env_file.write_text(json.dumps(env, indent=2) + "\n")
        print(f"[create_user] updated {args.env_file}")
        print("[create_user] next step: python refresh_vk.py")


if __name__ == "__main__":
    main()

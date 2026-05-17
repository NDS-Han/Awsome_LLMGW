"""AgentCore Optimization API client — Recommendations, Configuration Bundles, A/B Testing (Gateway Rules)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import botocore.session


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _region() -> str:
    return _env("AGENTCORE_REGION", _env("AWS_DEFAULT_REGION", "us-east-1"))


def _data_client():
    session = botocore.session.get_session()
    return session.create_client("bedrock-agentcore", region_name=_region())


def _control_client():
    session = botocore.session.get_session()
    return session.create_client("bedrock-agentcore-control", region_name=_region())


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def start_recommendation(
    name: str,
    evaluator_id: str,
    current_prompt: str,
    lookback_days: int = 7,
    rec_type: str = "SYSTEM_PROMPT_RECOMMENDATION",
) -> dict:
    """Start a recommendation run analyzing recent traces."""
    client = _data_client()

    now = datetime.now(timezone.utc)
    log_group_arn = _env("AGENTCORE_LOG_GROUP_ARN")
    service_name = _env("AGENTCORE_SERVICE_NAME")
    if not log_group_arn or not service_name:
        raise ValueError(
            "AGENTCORE_LOG_GROUP_ARN and AGENTCORE_SERVICE_NAME env vars are required "
            "for recommendations (agentTraces is a required parameter)"
        )

    agent_traces = {
        "cloudwatchLogs": {
            "logGroupArns": [log_group_arn],
            "serviceNames": [service_name],
            "startTime": now - timedelta(days=lookback_days),
            "endTime": now,
        }
    }

    evaluator_arn = evaluator_id
    if not evaluator_arn.startswith("arn:"):
        evaluator_arn = f"arn:aws:bedrock-agentcore:::evaluator/{evaluator_id}"

    config = {
        "systemPromptRecommendationConfig": {
            "systemPrompt": {"text": current_prompt},
            "agentTraces": agent_traces,
            "evaluationConfig": {
                "evaluators": [{"evaluatorArn": evaluator_arn}]
            },
        }
    }

    response = client.start_recommendation(
        name=name,
        type=rec_type,
        recommendationConfig=config,
        clientToken=str(uuid.uuid4()),
    )
    return {
        "recommendation_id": response.get("recommendationId", ""),
        "status": response.get("status", "PENDING"),
        "name": name,
        "type": rec_type,
        "evaluator_id": evaluator_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def get_recommendation(recommendation_id: str) -> dict:
    """Get recommendation status and result."""
    client = _data_client()
    resp = client.get_recommendation(recommendationId=recommendation_id)

    result = {
        "recommendation_id": resp.get("recommendationId", recommendation_id),
        "name": resp.get("name", ""),
        "status": resp.get("status", "UNKNOWN"),
        "type": resp.get("type", ""),
        "created_at": _iso(resp.get("createdAt")),
        "updated_at": _iso(resp.get("updatedAt")),
    }

    rec_result = resp.get("recommendationResult", {})
    sys_result = rec_result.get("systemPromptRecommendationResult", {})
    if sys_result:
        result["recommended_prompt"] = sys_result.get("recommendedSystemPrompt", "")
        result["error_code"] = sys_result.get("errorCode")
        result["error_message"] = sys_result.get("errorMessage")
        bundle_info = sys_result.get("configurationBundle")
        if bundle_info:
            result["bundle_arn"] = bundle_info.get("bundleArn", "")
            result["bundle_version"] = bundle_info.get("versionId", "")

    return result


def list_recommendations() -> list[dict]:
    """List all recommendations."""
    client = _data_client()
    resp = client.list_recommendations()
    items = resp.get("recommendationSummaries", resp.get("recommendations", []))
    return [
        {
            "recommendation_id": item.get("recommendationId", ""),
            "name": item.get("name", ""),
            "status": item.get("status", ""),
            "type": item.get("type", ""),
            "created_at": _iso(item.get("createdAt")),
        }
        for item in items
    ]


def delete_recommendation(recommendation_id: str) -> dict:
    client = _data_client()
    client.delete_recommendation(recommendationId=recommendation_id)
    return {"deleted": True, "recommendation_id": recommendation_id}


# ---------------------------------------------------------------------------
# Configuration Bundles
# ---------------------------------------------------------------------------

def create_bundle(bundle_name: str, system_prompt: str, description: str = "") -> dict:
    """Create a configuration bundle with system prompt component."""
    client = _control_client()
    import json

    runtime_arn = _env("AGENTCORE_RUNTIME_ARN")
    if not runtime_arn:
        raise ValueError("AGENTCORE_RUNTIME_ARN env var required for configuration bundles")

    resp = client.create_configuration_bundle(
        bundleName=bundle_name,
        description=description or f"Agent configuration: {bundle_name}",
        components={
            runtime_arn: {
                "configuration": json.dumps({"systemPrompt": system_prompt}),
            }
        },
        commitMessage=f"Create bundle {bundle_name}",
        clientToken=str(uuid.uuid4()),
    )
    return {
        "bundle_id": resp.get("bundleId", ""),
        "bundle_arn": resp.get("bundleArn", ""),
        "bundle_name": bundle_name,
        "version_id": resp.get("versionId", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def update_bundle(bundle_id: str, system_prompt: str, commit_message: str = "") -> dict:
    """Update a configuration bundle (creates new version)."""
    client = _control_client()
    import json

    runtime_arn = _env("AGENTCORE_RUNTIME_ARN")
    if not runtime_arn:
        raise ValueError("AGENTCORE_RUNTIME_ARN env var required for configuration bundles")

    current = client.get_configuration_bundle(bundleId=bundle_id)
    current_version = current.get("versionId", "")

    resp = client.update_configuration_bundle(
        bundleId=bundle_id,
        components={
            runtime_arn: {
                "configuration": json.dumps({"systemPrompt": system_prompt}),
            }
        },
        parentVersionIds=[current_version],
        commitMessage=commit_message or "Update system prompt",
    )
    return {
        "bundle_id": bundle_id,
        "bundle_arn": current.get("bundleArn", ""),
        "version_id": resp.get("versionId", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_bundle(bundle_id: str, version_id: Optional[str] = None) -> dict:
    """Get a configuration bundle (optionally a specific version)."""
    client = _control_client()
    if version_id:
        resp = client.get_configuration_bundle_version(bundleId=bundle_id, versionId=version_id)
    else:
        resp = client.get_configuration_bundle(bundleId=bundle_id)

    lineage = resp.get("lineageMetadata", {})
    commit_message = lineage.get("commitMessage", "")
    parent_versions = lineage.get("parentVersionIds", [])
    branch = lineage.get("branchName", "")

    # Extract recommendation_id from commit message if present
    recommendation_id = ""
    if "recommendation" in commit_message.lower():
        parts = commit_message.split()
        for p in parts:
            if p.startswith("rec-"):
                recommendation_id = p
                break

    # Try to extract system_prompt from components (may be empty per API behavior)
    import json
    system_prompt = ""
    components = resp.get("components", {})
    for _arn, comp in components.items():
        config = comp.get("configuration", {})
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                pass
        if isinstance(config, dict):
            system_prompt = config.get("systemPrompt", config.get("text", ""))
        if system_prompt:
            break

    result = {
        "bundle_id": resp.get("bundleId", bundle_id),
        "bundle_arn": resp.get("bundleArn", ""),
        "bundle_name": resp.get("bundleName", ""),
        "version_id": resp.get("versionId", ""),
        "description": resp.get("description", ""),
        "system_prompt": system_prompt,
        "created_at": _iso(resp.get("createdAt")),
        "version_created_at": _iso(resp.get("versionCreatedAt")),
        "commit_message": commit_message,
        "parent_versions": parent_versions,
        "branch": branch,
        "recommendation_id": recommendation_id,
    }

    # If no system_prompt from bundle, try loading from linked recommendation
    if not system_prompt and recommendation_id:
        try:
            rec = get_recommendation(recommendation_id)
            result["system_prompt"] = rec.get("recommended_prompt", "")
            result["prompt_source"] = "recommendation"
        except Exception:
            pass

    return result


def list_bundles() -> list[dict]:
    """List all configuration bundles."""
    client = _control_client()
    resp = client.list_configuration_bundles()
    items = resp.get("items", resp.get("configurationBundles", []))
    return [
        {
            "bundle_id": item.get("bundleId", ""),
            "bundle_name": item.get("bundleName", ""),
            "description": item.get("description", ""),
            "created_at": _iso(item.get("createdAt")),
        }
        for item in items
    ]


def list_bundle_versions(bundle_id: str) -> list[dict]:
    """List versions of a configuration bundle."""
    client = _control_client()
    resp = client.list_configuration_bundle_versions(bundleId=bundle_id)
    items = resp.get("items", resp.get("versions", []))
    results = []
    for item in items:
        lineage = item.get("lineageMetadata", {})
        results.append({
            "version_id": item.get("versionId", ""),
            "created_at": _iso(item.get("versionCreatedAt")),
            "commit_message": lineage.get("commitMessage", ""),
            "parent_versions": lineage.get("parentVersionIds", []),
            "branch": lineage.get("branchName", ""),
        })
    return results




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)

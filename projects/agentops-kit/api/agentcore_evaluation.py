"""AgentCore Evaluation API wrapper.

Provides:
- Online Evaluation Config CRUD (auto-sampling of live traffic)
- On-demand evaluation (single session/trace)
- Batch evaluation (multi-session)
- Evaluator listing
- Results retrieval from CloudWatch Logs
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import boto3
from botocore.config import Config

REGION = os.getenv("AGENTCORE_REGION", "us-east-1")
AGENT_ID = os.getenv("AGENTCORE_AGENT_ID", "")
LOG_GROUP_NAME = os.getenv("AGENTCORE_LOG_GROUP_NAME", "")
SERVICE_NAME = os.getenv("AGENTCORE_SERVICE_NAME", "")
EVAL_ROLE_ARN = os.getenv("AGENTCORE_EVAL_ROLE_ARN", "")

_client_config = Config(
    region_name=REGION,
    retries={"max_attempts": 2, "mode": "adaptive"},
)


def _cp_client():
    return boto3.client("bedrock-agentcore-control", config=_client_config)


def _dp_client():
    return boto3.client("bedrock-agentcore", config=_client_config)


def _logs_client():
    return boto3.client("logs", region_name=REGION)


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------

def list_evaluators() -> list[dict]:
    resp = _cp_client().list_evaluators()
    evaluators = resp.get("evaluators", [])
    return [
        {
            "evaluator_id": e["evaluatorId"],
            "name": e.get("evaluatorName", e["evaluatorId"]),
            "description": e.get("description", ""),
            "type": e.get("evaluatorType", "Builtin"),
            "level": e.get("level", "TRACE"),
            "status": e.get("status", "ACTIVE"),
        }
        for e in evaluators
    ]


# ---------------------------------------------------------------------------
# Online Evaluation Config
# ---------------------------------------------------------------------------

def list_online_configs() -> list[dict]:
    resp = _cp_client().list_online_evaluation_configs()
    configs = resp.get("onlineEvaluationConfigs", [])
    results = []
    client = _cp_client()
    for c in configs:
        config_id = c.get("onlineEvaluationConfigId", "")
        if config_id:
            try:
                detail = client.get_online_evaluation_config(
                    onlineEvaluationConfigId=config_id
                )
                results.append(_format_online_config(detail))
            except Exception:
                results.append(_format_online_config(c))
        else:
            results.append(_format_online_config(c))
    return results


def get_online_config(config_id: str) -> dict:
    resp = _cp_client().get_online_evaluation_config(
        onlineEvaluationConfigId=config_id
    )
    return _format_online_config(resp)


def create_online_config(
    name: str,
    evaluator_ids: list[str],
    sampling_rate: float = 100.0,
    description: str = "",
) -> dict:
    if not EVAL_ROLE_ARN:
        raise ValueError(
            "AGENTCORE_EVAL_ROLE_ARN env var is required for online evaluation config creation"
        )
    if not LOG_GROUP_NAME:
        raise ValueError(
            "AGENTCORE_LOG_GROUP_NAME env var is required for online evaluation config creation"
        )
    if not SERVICE_NAME:
        raise ValueError(
            "AGENTCORE_SERVICE_NAME env var is required for online evaluation config creation"
        )

    params: dict = {
        "onlineEvaluationConfigName": name,
        "evaluationExecutionRoleArn": EVAL_ROLE_ARN,
        "rule": {
            "samplingConfig": {"samplingPercentage": sampling_rate},
        },
        "evaluators": [{"evaluatorId": eid} for eid in evaluator_ids],
        "dataSourceConfig": {
            "cloudWatchLogs": {
                "logGroupNames": [LOG_GROUP_NAME],
                "serviceNames": [SERVICE_NAME],
            }
        },
        "enableOnCreate": True,
    }
    if description:
        params["description"] = description

    resp = _cp_client().create_online_evaluation_config(**params)
    config_id = resp.get("onlineEvaluationConfigId", "")
    # Wait briefly for it to become ACTIVE
    for _ in range(5):
        time.sleep(2)
        try:
            cfg = get_online_config(config_id)
            if cfg["status"] == "ACTIVE":
                return cfg
        except Exception:
            pass
    return get_online_config(config_id)


def update_online_config(
    config_id: str,
    sampling_rate: Optional[float] = None,
    evaluator_ids: Optional[list[str]] = None,
    enabled: Optional[bool] = None,
) -> dict:
    params: dict = {"onlineEvaluationConfigId": config_id}
    if sampling_rate is not None:
        params["rule"] = {"samplingConfig": {"samplingPercentage": sampling_rate}}
    if evaluator_ids is not None:
        params["evaluators"] = [{"evaluatorId": eid} for eid in evaluator_ids]
    if enabled is not None:
        params["executionStatus"] = "ENABLED" if enabled else "DISABLED"

    _cp_client().update_online_evaluation_config(**params)
    time.sleep(1)
    return get_online_config(config_id)


def delete_online_config(config_id: str) -> dict:
    _cp_client().delete_online_evaluation_config(
        onlineEvaluationConfigId=config_id
    )
    return {"deleted": True, "config_id": config_id}


def _extract_output_log_group(raw: dict) -> str:
    """Extract output log group from various possible response structures."""
    # Try outputConfig (documented shape)
    oc = raw.get("outputConfig", {})
    for key in ("cloudWatchConfig", "cloudWatchLogs", "cloudWatch"):
        cw = oc.get(key, {})
        if isinstance(cw, dict):
            lg = cw.get("logGroupName", "")
            if lg:
                return lg
            names = cw.get("logGroupNames", [])
            if isinstance(names, list) and names:
                return names[0]

    # Try top-level outputLogGroupName / resultsLogGroup
    for key in ("outputLogGroupName", "resultsLogGroup", "outputLogGroup"):
        val = raw.get(key, "")
        if val:
            return val

    return ""


def _format_online_config(raw: dict) -> dict:
    evaluators = raw.get("evaluators", [])
    output_log_group = _extract_output_log_group(raw)

    return {
        "config_id": raw.get("onlineEvaluationConfigId", ""),
        "config_name": raw.get("onlineEvaluationConfigName", ""),
        "description": raw.get("description", ""),
        "status": raw.get("status", ""),
        "execution_status": raw.get("executionStatus", ""),
        "sampling_rate": raw.get("rule", {}).get("samplingConfig", {}).get("samplingPercentage", 0),
        "evaluators": [e.get("evaluatorId", "") for e in evaluators],
        "output_log_group": output_log_group,
        "created_at": str(raw.get("createdAt", "")),
        "updated_at": str(raw.get("updatedAt", "")),
    }


# ---------------------------------------------------------------------------
# On-Demand Evaluation (single session/trace)
# ---------------------------------------------------------------------------

def run_on_demand(
    evaluator_ids: list[str],
    session_id: str,
    trace_id: Optional[str] = None,
    look_back_hours: int = 1,
) -> list[dict]:
    from bedrock_agentcore.evaluation.client import EvaluationClient

    client = EvaluationClient(region_name=REGION)
    results = client.run(
        evaluator_ids=evaluator_ids,
        session_id=session_id,
        agent_id=AGENT_ID or None,
        log_group_name=LOG_GROUP_NAME if not AGENT_ID else None,
        trace_id=trace_id.replace("-", "") if trace_id else None,
        look_back_time=timedelta(hours=look_back_hours),
    )
    return [
        {
            "evaluator_id": r.get("evaluatorId", ""),
            "score": r.get("value"),
            "label": _score_label(r.get("value", 0)),
            "explanation": r.get("explanation", ""),
            "trace_id": r.get("traceId", ""),
            "session_id": r.get("sessionId", ""),
        }
        for r in results
        if r.get("value") is not None
    ]


# ---------------------------------------------------------------------------
# Batch Evaluation
# ---------------------------------------------------------------------------

def _sanitize_batch_name(name: str) -> str:
    """Ensure name matches pattern: [a-zA-Z][a-zA-Z0-9_]{0,47}"""
    import re
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if not sanitized or not sanitized[0].isalpha():
        sanitized = "batch_" + sanitized
    return sanitized[:48]


def start_batch(
    name: str,
    evaluator_ids: list[str],
) -> dict:
    if not LOG_GROUP_NAME:
        raise ValueError("AGENTCORE_LOG_GROUP_NAME env var is required for batch evaluation")
    if not SERVICE_NAME:
        raise ValueError("AGENTCORE_SERVICE_NAME env var is required for batch evaluation")

    params: dict = {
        "batchEvaluationName": _sanitize_batch_name(name),
        "evaluators": [{"evaluatorId": eid} for eid in evaluator_ids],
        "dataSourceConfig": {
            "cloudWatchLogs": {
                "logGroupNames": [LOG_GROUP_NAME],
                "serviceNames": [SERVICE_NAME],
            }
        },
    }
    resp = _dp_client().start_batch_evaluation(**params)
    return {
        "batch_id": resp.get("batchEvaluationId", ""),
        "status": resp.get("status", "STARTING"),
    }


def get_batch(batch_id: str) -> dict:
    resp = _dp_client().get_batch_evaluation(batchEvaluationId=batch_id)
    results = resp.get("evaluationResults", {})
    summaries = results.get("evaluatorSummaries", [])
    session_results = results.get("sessionResults", [])

    formatted_sessions = []
    for sr in session_results:
        session_id = sr.get("sessionId", "")
        for er in sr.get("evaluatorResults", []):
            formatted_sessions.append({
                "evaluator_id": er.get("evaluatorId", ""),
                "score": er.get("value", er.get("score")),
                "label": _score_label(er.get("value", er.get("score", 0))),
                "explanation": er.get("explanation", ""),
                "trace_id": er.get("traceId", ""),
                "session_id": session_id,
                "timestamp": str(er.get("timestamp", "")),
            })

    output = {
        "batch_id": resp.get("batchEvaluationId", ""),
        "name": resp.get("batchEvaluationName", ""),
        "status": resp.get("status", ""),
        "created_at": str(resp.get("createdAt", "")),
        "sessions_completed": results.get("numberOfSessionsCompleted", 0),
        "sessions_in_progress": results.get("numberOfSessionsInProgress", 0),
        "sessions_failed": results.get("numberOfSessionsFailed", 0),
        "total_sessions": results.get("totalNumberOfSessions", 0),
        "evaluator_summaries": [
            {
                "evaluator_id": s.get("evaluatorId", ""),
                "average_score": s.get("statistics", {}).get("averageScore", 0),
                "total_evaluated": s.get("totalEvaluated", 0),
                "total_failed": s.get("totalFailed", 0),
            }
            for s in summaries
        ],
    }

    if formatted_sessions:
        output["results"] = formatted_sessions
        output["results_summary"] = _compute_summary(formatted_sessions)

    return output


def list_batches() -> list[dict]:
    resp = _dp_client().list_batch_evaluations()
    return [
        {
            "batch_id": b.get("batchEvaluationId", ""),
            "name": b.get("batchEvaluationName", ""),
            "status": b.get("status", ""),
            "created_at": str(b.get("createdAt", "")),
        }
        for b in resp.get("batchEvaluations", [])
    ]


# ---------------------------------------------------------------------------
# Results from CloudWatch Logs
# ---------------------------------------------------------------------------

def get_online_results(
    config_id: str,
    hours: int = 24,
    limit: int = 100,
) -> dict:
    """Fetch evaluation results from the online config's output CloudWatch Log Group."""
    cfg = get_online_config(config_id)
    log_group = cfg.get("output_log_group", "")

    if not log_group:
        fallbacks = [
            f"/aws/bedrock-agentcore/evaluations/online/{config_id}",
            f"/aws/bedrock-agentcore/evaluations/results/{config_id}",
        ]
        for fb in fallbacks:
            result = _query_eval_log_group(fb, hours, limit)
            if result.get("results"):
                return result
        return {"results": [], "summary": {}, "error": "No output log group found"}

    return _query_eval_log_group(log_group, hours, limit)


def get_batch_results(batch_id: str, hours: int = 24, limit: int = 100) -> dict:
    """Fetch results from a batch evaluation's output log group."""
    batch = get_batch(batch_id)
    # Batch output goes to a predictable log group
    log_group = f"/aws/bedrock-agentcore/evaluations/results/{batch_id}"
    try:
        return _query_eval_log_group(log_group, hours, limit)
    except Exception:
        return {"results": [], "summary": batch}


def _query_eval_log_group(log_group: str, hours: int, limit: int) -> dict:
    logs = _logs_client()
    start_time = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000)
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)

    results = []
    try:
        resp = logs.filter_log_events(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            limit=limit,
        )
        for event in resp.get("events", []):
            try:
                parsed = json.loads(event.get("message", "{}"))
                results.append(_format_eval_result(parsed, event.get("timestamp", 0)))
            except (json.JSONDecodeError, KeyError):
                continue
    except logs.exceptions.ResourceNotFoundException:
        return {"results": [], "summary": {}, "error": f"Log group not found: {log_group}"}
    except Exception as e:
        return {"results": [], "summary": {}, "error": str(e)}

    summary = _compute_summary(results)
    return {"results": results, "summary": summary}


def _format_eval_result(raw: dict, timestamp_ms: int) -> dict:
    attrs = raw.get("attributes", {})

    # OTEL/EMF format (AgentCore evaluation logs)
    evaluator_id = (
        attrs.get("gen_ai.evaluation.name")
        or raw.get("evaluatorId")
        or raw.get("evaluator_id")
        or ""
    )
    score = attrs.get("gen_ai.evaluation.score.value")
    if score is None:
        score = raw.get("value") if raw.get("value") is not None else raw.get("score")
    # Also check top-level metric key (e.g. "Builtin.Correctness": 1.0)
    if score is None and evaluator_id:
        score = raw.get(evaluator_id)

    explanation = (
        attrs.get("gen_ai.evaluation.explanation")
        or raw.get("explanation")
        or ""
    )
    label = (
        attrs.get("gen_ai.evaluation.score.label")
        or raw.get("label")
        or _score_label(score if score is not None else 0)
    )
    session_id = (
        attrs.get("session.id")
        or raw.get("sessionId")
        or raw.get("session_id")
        or ""
    )
    trace_id = (
        raw.get("traceId")
        or attrs.get("gen_ai.response.id")
        or raw.get("trace_id")
        or ""
    )

    # Timestamp: prefer OTEL timeUnixNano, fallback to event timestamp
    time_nano = raw.get("timeUnixNano")
    if time_nano:
        ts = datetime.fromtimestamp(time_nano / 1e9, tz=timezone.utc).isoformat()
    elif timestamp_ms:
        ts = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
    else:
        ts = ""

    return {
        "evaluator_id": evaluator_id,
        "score": score,
        "label": label,
        "explanation": explanation,
        "trace_id": trace_id,
        "session_id": session_id,
        "timestamp": ts,
    }


def _compute_summary(results: list[dict]) -> dict:
    if not results:
        return {"count": 0, "avg_score": 0, "by_evaluator": {}}

    by_evaluator: dict[str, list[float]] = {}
    for r in results:
        eid = r.get("evaluator_id", "unknown")
        score = r.get("score")
        if score is not None:
            by_evaluator.setdefault(eid, []).append(score)

    all_scores = [r["score"] for r in results if r.get("score") is not None]
    avg = sum(all_scores) / len(all_scores) if all_scores else 0

    evaluator_summary = {}
    for eid, scores in by_evaluator.items():
        evaluator_summary[eid] = {
            "count": len(scores),
            "avg_score": round(sum(scores) / len(scores), 4),
            "min_score": round(min(scores), 4),
            "max_score": round(max(scores), 4),
        }

    return {
        "count": len(results),
        "avg_score": round(avg, 4),
        "by_evaluator": evaluator_summary,
    }


def _score_label(score: float) -> str:
    if score is None:
        return "N/A"
    if score >= 0.9:
        return "Excellent"
    if score >= 0.8:
        return "Very Good"
    if score >= 0.6:
        return "Good"
    if score >= 0.4:
        return "Fair"
    return "Poor"

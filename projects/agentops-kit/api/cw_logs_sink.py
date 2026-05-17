"""CloudWatch Logs sink for analytics events."""

import os
import json
import socket

import boto3

from api.analytics import AnalyticsSink, AnalyticsEvent


REGION = os.getenv("AWS_REGION", "us-east-1")
LOG_GROUP = "/agentops/analytics"


class CloudWatchLogsSink(AnalyticsSink):
    """Durable sink — writes analytics events to CloudWatch Logs."""

    accepts_pii = False
    name = "cloudwatch_logs"

    def __init__(self, log_group: str = LOG_GROUP, log_stream: str = ""):
        self._log_group = log_group
        self._log_stream = log_stream or f"bff-{socket.gethostname()}-{os.getpid()}"
        self._client = boto3.client("logs", region_name=REGION)
        self._sequence_token: str | None = None
        self._stream_created = False

    def _ensure_stream(self):
        if self._stream_created:
            return
        try:
            self._client.create_log_stream(
                logGroupName=self._log_group,
                logStreamName=self._log_stream,
            )
        except self._client.exceptions.ResourceAlreadyExistsException:
            pass
        except Exception as e:
            print(f"[cw_logs_sink] create stream failed: {e}")
        self._stream_created = True

    def write(self, events: list[AnalyticsEvent]):
        if not events:
            return
        self._ensure_stream()
        try:
            log_events = []
            for event in events:
                log_events.append({
                    "timestamp": int(event.timestamp.timestamp() * 1000),
                    "message": json.dumps(event.to_dict(include_pii=False), default=str),
                })
            log_events.sort(key=lambda x: x["timestamp"])

            kwargs = {
                "logGroupName": self._log_group,
                "logStreamName": self._log_stream,
                "logEvents": log_events,
            }
            if self._sequence_token:
                kwargs["sequenceToken"] = self._sequence_token

            resp = self._client.put_log_events(**kwargs)
            self._sequence_token = resp.get("nextSequenceToken")
        except Exception as e:
            print(f"[cw_logs_sink] write failed: {e}")
            self._sequence_token = None

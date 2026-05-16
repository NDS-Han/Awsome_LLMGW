"""
CloudWatch Anomaly Detection 알람 생성 스크립트.
AgentCore/GenAI 네임스페이스의 핵심 메트릭에 대해 이상 탐지 알람을 설정합니다.

Usage:
    python -m infra.setup_anomaly_alarms [--delete]
"""

import os
import sys
import argparse

import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
RUNTIME_NS = "AWS/Bedrock-AgentCore"
OTEL_NS = "bedrock-agentcore"
AGENT_ID = os.getenv("AGENTCORE_AGENT_ID", "agentops-demo")
ALARM_PREFIX = "agentops-anomaly"
BAND_WIDTH = 2  # standard deviations

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")


def _get_account_id() -> str:
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def _runtime_dims() -> list[dict]:
    runtime_arn = f"arn:aws:bedrock-agentcore:{REGION}:{_get_account_id()}:runtime/{AGENT_ID}"
    name = AGENT_ID.rsplit("-", 1)[0] + "::DEFAULT" if "-" in AGENT_ID else AGENT_ID + "::DEFAULT"
    return [
        {"Name": "Resource", "Value": runtime_arn},
        {"Name": "Operation", "Value": "InvokeAgentRuntime"},
        {"Name": "Name", "Value": name},
    ]


def _token_dims() -> list[dict]:
    return [
        {"Name": "server.address", "Value": f"bedrock-runtime.{REGION}.amazonaws.com"},
        {"Name": "gen_ai.operation.name", "Value": "chat"},
        {"Name": "server.port", "Value": "443"},
        {"Name": "gen_ai.request.model", "Value": BEDROCK_MODEL_ID},
        {"Name": "gen_ai.token.type", "Value": "input"},
        {"Name": "gen_ai.system", "Value": "aws.bedrock"},
    ]


ALARMS = [
    {
        "suffix": "latency",
        "namespace": RUNTIME_NS,
        "metric_name": "Latency",
        "display_name": "Invocation Latency Anomaly",
        "stat": "Average",
        "dims_fn": _runtime_dims,
        "comparison": "GreaterThanUpperThreshold",
    },
    {
        "suffix": "tokens",
        "namespace": OTEL_NS,
        "metric_name": "gen_ai.client.token.usage",
        "display_name": "Token Usage Anomaly",
        "stat": "Sum",
        "dims_fn": _token_dims,
        "comparison": "GreaterThanUpperThreshold",
    },
    {
        "suffix": "errors",
        "namespace": RUNTIME_NS,
        "metric_name": "Errors",
        "display_name": "Error Rate Anomaly",
        "stat": "Sum",
        "dims_fn": _runtime_dims,
        "comparison": "GreaterThanUpperThreshold",
    },
]


def create_alarms(sns_topic_arn: str | None = None):
    cw = boto3.client("cloudwatch", region_name=REGION)

    for alarm_def in ALARMS:
        alarm_name = f"{ALARM_PREFIX}-{alarm_def['suffix']}"
        ns = alarm_def["namespace"]
        dims = alarm_def["dims_fn"]()
        print(f"Creating anomaly detector for {ns}/{alarm_def['metric_name']}...")

        try:
            cw.put_anomaly_detector(
                Namespace=ns,
                MetricName=alarm_def["metric_name"],
                Dimensions=dims,
                Stat=alarm_def["stat"],
            )
            print(f"  Anomaly detector created: {alarm_def['metric_name']}")
        except Exception as e:
            print(f"  Anomaly detector already exists or error: {e}")

        alarm_kwargs = {
            "AlarmName": alarm_name,
            "AlarmDescription": alarm_def["display_name"],
            "ComparisonOperator": alarm_def["comparison"],
            "EvaluationPeriods": 3,
            "DatapointsToAlarm": 2,
            "TreatMissingData": "notBreaching",
            "Metrics": [
                {
                    "Id": "m1",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": ns,
                            "MetricName": alarm_def["metric_name"],
                            "Dimensions": dims,
                        },
                        "Period": 300,
                        "Stat": alarm_def["stat"],
                    },
                    "ReturnData": True,
                },
                {
                    "Id": "ad1",
                    "Expression": f"ANOMALY_DETECTION_BAND(m1, {BAND_WIDTH})",
                    "Label": f"{alarm_def['metric_name']} anomaly band",
                    "ReturnData": True,
                },
            ],
            "ThresholdMetricId": "ad1",
        }

        if sns_topic_arn:
            alarm_kwargs["AlarmActions"] = [sns_topic_arn]
            alarm_kwargs["OKActions"] = [sns_topic_arn]

        cw.put_metric_alarm(**alarm_kwargs)
        print(f"  Alarm created: {alarm_name}")

    print(f"\nAll {len(ALARMS)} anomaly alarms created successfully.")


def delete_alarms():
    cw = boto3.client("cloudwatch", region_name=REGION)
    alarm_names = [f"{ALARM_PREFIX}-{a['suffix']}" for a in ALARMS]

    print(f"Deleting alarms: {alarm_names}")
    cw.delete_alarms(AlarmNames=alarm_names)

    for alarm_def in ALARMS:
        ns = alarm_def["namespace"]
        dims = alarm_def["dims_fn"]()
        try:
            cw.delete_anomaly_detector(
                Namespace=ns,
                MetricName=alarm_def["metric_name"],
                Dimensions=dims,
                Stat=alarm_def["stat"],
            )
            print(f"  Deleted anomaly detector: {alarm_def['metric_name']}")
        except Exception as e:
            print(f"  Could not delete detector {alarm_def['metric_name']}: {e}")

    print("All alarms deleted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup CloudWatch Anomaly Detection alarms")
    parser.add_argument("--delete", action="store_true", help="Delete existing alarms")
    parser.add_argument("--sns-topic", type=str, default=None, help="SNS topic ARN for notifications")
    args = parser.parse_args()

    if args.delete:
        delete_alarms()
    else:
        create_alarms(sns_topic_arn=args.sns_topic)

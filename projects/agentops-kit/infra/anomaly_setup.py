"""
CloudWatch Anomaly Detection 알람 설정.

주요 GenAI 메트릭에 대해 anomaly detection 알람을 생성한다.
Usage: python infra/anomaly_setup.py
"""

import os
import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
NAMESPACE = "AgentCore/GenAI"
PREFIX = "agentops-anomaly"

ALARMS = [
    {
        "name": f"{PREFIX}-latency",
        "description": "Invocation Latency",
        "metric": "genai.invocation.latency",
        "stat": "Average",
        "period": 300,
        "threshold_band": 2,
    },
    {
        "name": f"{PREFIX}-errors",
        "description": "Error Rate",
        "metric": "genai.error.count",
        "stat": "Sum",
        "period": 300,
        "threshold_band": 3,
    },
    {
        "name": f"{PREFIX}-tokens",
        "description": "Token Usage per Call",
        "metric": "genai.token.input",
        "stat": "Average",
        "period": 300,
        "threshold_band": 2,
    },
]


def create_anomaly_alarms():
    cw = boto3.client("cloudwatch", region_name=REGION)

    for alarm_def in ALARMS:
        anomaly_id = alarm_def["name"].replace("-", "_")

        cw.put_anomaly_detector(
            Namespace=NAMESPACE,
            MetricName=alarm_def["metric"],
            Stat=alarm_def["stat"],
        )

        cw.put_metric_alarm(
            AlarmName=alarm_def["name"],
            AlarmDescription=alarm_def["description"],
            ActionsEnabled=False,
            Metrics=[
                {
                    "Id": "m1",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": NAMESPACE,
                            "MetricName": alarm_def["metric"],
                        },
                        "Period": alarm_def["period"],
                        "Stat": alarm_def["stat"],
                    },
                    "ReturnData": True,
                },
                {
                    "Id": "ad1",
                    "Expression": f"ANOMALY_DETECTION_BAND(m1, {alarm_def['threshold_band']})",
                    "Label": f"{alarm_def['metric']} (expected)",
                    "ReturnData": True,
                },
            ],
            ComparisonOperator="LessThanLowerOrGreaterThanUpperThreshold",
            ThresholdMetricId="ad1",
            TreatMissingData="notBreaching",
            EvaluationPeriods=3,
            DatapointsToAlarm=2,
        )

        print(f"Alarm '{alarm_def['name']}' created")

    print(f"All {len(ALARMS)} anomaly alarms configured in {REGION}")


if __name__ == "__main__":
    create_anomaly_alarms()

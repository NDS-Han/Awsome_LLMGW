"""
CloudWatch Dashboard 생성.

AgentOps GenAI 메트릭을 위한 6-위젯 대시보드를 생성한다.
Usage: python infra/dashboard.py
"""

import os
import json
import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
NAMESPACE = "AgentCore/GenAI"
DASHBOARD_NAME = "agentops-genai"


def create_dashboard():
    cw = boto3.client("cloudwatch", region_name=REGION)

    widgets = [
        {
            "type": "metric",
            "x": 0, "y": 0, "width": 12, "height": 6,
            "properties": {
                "title": "Invocation Latency (ms)",
                "metrics": [
                    [NAMESPACE, "genai.invocation.latency", {"stat": "Average", "label": "Avg"}],
                    [NAMESPACE, "genai.invocation.latency", {"stat": "p99", "label": "P99"}],
                ],
                "period": 60,
                "region": REGION,
                "view": "timeSeries",
                "yAxis": {"left": {"label": "ms", "min": 0}},
            },
        },
        {
            "type": "metric",
            "x": 12, "y": 0, "width": 12, "height": 6,
            "properties": {
                "title": "Token Usage",
                "metrics": [
                    [NAMESPACE, "genai.token.input", {"stat": "Sum", "label": "Input"}],
                    [NAMESPACE, "genai.token.output", {"stat": "Sum", "label": "Output"}],
                ],
                "period": 60,
                "region": REGION,
                "view": "timeSeries",
                "stacked": True,
            },
        },
        {
            "type": "metric",
            "x": 0, "y": 6, "width": 8, "height": 6,
            "properties": {
                "title": "Estimated Cost (USD)",
                "metrics": [
                    [NAMESPACE, "genai.cost.usd", {"stat": "Sum", "label": "Cost"}],
                ],
                "period": 300,
                "region": REGION,
                "view": "timeSeries",
                "yAxis": {"left": {"label": "USD", "min": 0}},
            },
        },
        {
            "type": "metric",
            "x": 8, "y": 6, "width": 8, "height": 6,
            "properties": {
                "title": "Invocation Count & Errors",
                "metrics": [
                    [NAMESPACE, "genai.invocation.count", {"stat": "Sum", "label": "Invocations"}],
                    [NAMESPACE, "genai.error.count", {"stat": "Sum", "label": "Errors", "color": "#d62728"}],
                ],
                "period": 60,
                "region": REGION,
                "view": "timeSeries",
            },
        },
        {
            "type": "metric",
            "x": 16, "y": 6, "width": 8, "height": 6,
            "properties": {
                "title": "Guardrail Violations",
                "metrics": [
                    [NAMESPACE, "genai.guardrail.violations", {"stat": "Sum", "label": "Violations"}],
                ],
                "period": 60,
                "region": REGION,
                "view": "timeSeries",
                "yAxis": {"left": {"min": 0}},
            },
        },
        {
            "type": "metric",
            "x": 0, "y": 12, "width": 24, "height": 6,
            "properties": {
                "title": "Tool Call Distribution",
                "metrics": [
                    [NAMESPACE, "genai.tool.calls", "tool.name", "query_sales_data", {"stat": "Sum"}],
                    [NAMESPACE, "genai.tool.calls", "tool.name", "analyze_reviews", {"stat": "Sum"}],
                    [NAMESPACE, "genai.tool.calls", "tool.name", "check_delivery_performance", {"stat": "Sum"}],
                    [NAMESPACE, "genai.tool.calls", "tool.name", "get_seller_metrics", {"stat": "Sum"}],
                ],
                "period": 300,
                "region": REGION,
                "view": "bar",
            },
        },
    ]

    body = json.dumps({"widgets": widgets})
    cw.put_dashboard(DashboardName=DASHBOARD_NAME, DashboardBody=body)
    print(f"Dashboard '{DASHBOARD_NAME}' created in {REGION}")


if __name__ == "__main__":
    create_dashboard()

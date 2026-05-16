# AgentCore Runtime 컨테이너 (ARM64)
# CodeBuild에서 빌드되어 ECR로 푸시됨.

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 비루트 사용자 생성 (보안)
RUN groupadd --system --gid 1001 appgroup \
    && useradd --system --uid 1001 --gid appgroup --home /app --shell /usr/sbin/nologin appuser

# 의존성 먼저 설치 (레이어 캐시)
COPY agent/requirements.txt /tmp/agent-requirements.txt
RUN pip install --no-cache-dir -r /tmp/agent-requirements.txt

# 앱 코드
COPY agent/ /app/agent/
RUN chown -R appuser:appgroup /app

# AgentCore Runtime은 8080 포트에서 HTTP 서버 실행 기대
EXPOSE 8080

USER appuser

ENV OTEL_SERVICE_NAME=ecommerce_analytics
ENV OTEL_PYTHON_DISTRO=aws_distro
ENV OTEL_PYTHON_CONFIGURATOR=aws_configurator
ENV OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
ENV OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
ENV AGENT_OBSERVABILITY_ENABLED=true
ENV PYTHONUNBUFFERED=1

# opentelemetry-instrument로 ADOT 자동 계측 활성화
CMD ["opentelemetry-instrument", "python", "-m", "agent.agent"]

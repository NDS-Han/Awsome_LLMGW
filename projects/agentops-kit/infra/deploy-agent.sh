#!/usr/bin/env bash
# AgentCore Runtime 에이전트 배포 스크립트
# .env에서 필요한 환경변수를 읽어 agentcore launch에 전달한다.
#
# Usage:
#   bash infra/deploy-agent.sh                    # main 에이전트만 배포
#   bash infra/deploy-agent.sh --all              # main + specialist 3개 모두 배포
#   bash infra/deploy-agent.sh --agent reviews_specialist

set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Run 'bash infra/deploy.sh env' first."
  exit 1
fi

source "$ENV_FILE"

AGENT_REGION="${AGENTCORE_REGION:-us-east-1}"

# 에이전트 컨테이너에 주입할 환경변수 (Gateway 인증 + 모델 + OTEL)
COMMON_ENV=(
  --env "GATEWAY_URL=${GATEWAY_URL}"
  --env "COGNITO_CLIENT_ID=${COGNITO_CLIENT_ID}"
  --env "COGNITO_CLIENT_SECRET=${COGNITO_CLIENT_SECRET}"
  --env "COGNITO_TOKEN_ENDPOINT=${COGNITO_TOKEN_ENDPOINT}"
  --env "COGNITO_SCOPE=${COGNITO_SCOPE}"
  --env "BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID}"
  --env "AWS_REGION=${AGENT_REGION}"
  --env "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true"
)

deploy_agent() {
  local agent_name="$1"
  local role="${2:-}"
  local extra_env=()

  if [[ -n "$role" ]]; then
    extra_env+=(--env "AGENT_ROLE=${role}")
  fi

  echo "=== Deploying ${agent_name} ==="
  agentcore deploy \
    --agent "$agent_name" \
    --auto-update-on-conflict \
    "${COMMON_ENV[@]}" \
    "${extra_env[@]}"
  echo "=== ${agent_name} deployed ==="
  echo ""
}

DEPLOY_ALL=false
TARGET_AGENT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all) DEPLOY_ALL=true; shift ;;
    --agent) TARGET_AGENT="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -n "$TARGET_AGENT" ]]; then
  case "$TARGET_AGENT" in
    reviews_specialist)  deploy_agent "$TARGET_AGENT" "reviews" ;;
    logistics_specialist) deploy_agent "$TARGET_AGENT" "logistics" ;;
    *) deploy_agent "$TARGET_AGENT" ;;
  esac
elif [[ "$DEPLOY_ALL" == true ]]; then
  deploy_agent "ecommerce_analytics" "main"
  deploy_agent "reviews_specialist" "reviews"
  deploy_agent "logistics_specialist" "logistics"
else
  deploy_agent "ecommerce_analytics" "main"
fi

echo "Done."

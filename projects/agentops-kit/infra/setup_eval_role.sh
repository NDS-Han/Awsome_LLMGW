#!/usr/bin/env bash
# AgentCore Evaluation 실행 역할 생성/조회 스크립트
# 온라인 평가 Config가 사용하는 IAM Role을 생성하고 .env에 ARN을 추가한다.
#
# Usage:
#   bash infra/setup_eval_role.sh          # 역할 생성 또는 기존 역할 확인
#   bash infra/setup_eval_role.sh --delete  # 역할 삭제

set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME="AgentCoreEvalExecutionRole-${REGION}"
POLICY_NAME="AgentCoreEvalExecutionPolicy-${REGION}"
ENV_FILE=".env"

cmd="${1:-create}"

create_role() {
  echo "=== AgentCore Evaluation Role Setup ==="
  echo "Account: $ACCOUNT_ID | Region: $REGION"
  echo ""

  # Check if role already exists
  if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query "Role.Arn" --output text)
    echo "Role already exists: $ROLE_ARN"
  else
    echo "Creating role: $ROLE_NAME ..."

    TRUST_POLICY=$(cat <<'TRUST'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "ACCOUNT_PLACEHOLDER"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock-agentcore:REGION_PLACEHOLDER:ACCOUNT_PLACEHOLDER:*"
        }
      }
    }
  ]
}
TRUST
)
    TRUST_POLICY="${TRUST_POLICY//ACCOUNT_PLACEHOLDER/$ACCOUNT_ID}"
    TRUST_POLICY="${TRUST_POLICY//REGION_PLACEHOLDER/$REGION}"

    ROLE_ARN=$(aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document "$TRUST_POLICY" \
      --description "Execution role for AgentCore Online Evaluation" \
      --query "Role.Arn" --output text)

    echo "Created role: $ROLE_ARN"
  fi

  # Create or update policy
  EXEC_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:${REGION}:${ACCOUNT_ID}:*"
      ]
    },
    {
      "Sid": "CloudWatchLogsRead",
      "Effect": "Allow",
      "Action": [
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults",
        "logs:DescribeLogGroups"
      ],
      "Resource": [
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:aws/spans:*",
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*",
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/evaluations/*",
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:*"
      ]
    },
    {
      "Sid": "CloudWatchLogsWrite",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": [
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/evaluations/*",
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/evaluations/*:log-stream:*"
      ]
    }
  ]
}
EOF
)

  # Check if policy exists
  POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
  if aws iam get-policy --policy-arn "$POLICY_ARN" &>/dev/null; then
    echo "Updating existing policy ..."
    aws iam create-policy-version \
      --policy-arn "$POLICY_ARN" \
      --policy-document "$EXEC_POLICY" \
      --set-as-default > /dev/null
  else
    echo "Creating policy: $POLICY_NAME ..."
    POLICY_ARN=$(aws iam create-policy \
      --policy-name "$POLICY_NAME" \
      --policy-document "$EXEC_POLICY" \
      --description "Permissions for AgentCore Online Evaluation execution" \
      --query "Policy.Arn" --output text)
  fi

  # Attach policy to role
  aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN" 2>/dev/null || true
  echo "Policy attached: $POLICY_ARN"

  # Update .env
  if [[ -f "$ENV_FILE" ]]; then
    if grep -q "AGENTCORE_EVAL_ROLE_ARN" "$ENV_FILE"; then
      sed -i "s|^AGENTCORE_EVAL_ROLE_ARN=.*|AGENTCORE_EVAL_ROLE_ARN=$ROLE_ARN|" "$ENV_FILE"
    else
      echo "AGENTCORE_EVAL_ROLE_ARN=$ROLE_ARN" >> "$ENV_FILE"
    fi
    echo ""
    echo "Updated .env: AGENTCORE_EVAL_ROLE_ARN=$ROLE_ARN"
  else
    echo ""
    echo "Add to .env:"
    echo "AGENTCORE_EVAL_ROLE_ARN=$ROLE_ARN"
  fi

  echo ""
  echo "=== Done ==="
}

delete_role() {
  echo "Deleting eval role: $ROLE_NAME ..."
  POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

  aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN" 2>/dev/null || true
  aws iam delete-policy --policy-arn "$POLICY_ARN" 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_NAME" 2>/dev/null || true
  echo "Deleted."
}

case "$cmd" in
  create|"") create_role ;;
  --delete|delete) delete_role ;;
  *) echo "Usage: $0 {create|delete}"; exit 1 ;;
esac

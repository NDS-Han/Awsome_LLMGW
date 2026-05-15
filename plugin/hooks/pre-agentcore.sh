#!/bin/bash

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only handle agentcore commands
echo "$COMMAND" | grep -q 'agentcore' || exit 0

HAS_3A=false
[ -d ".3a" ] && HAS_3A=true

HAS_ROADMAP=false
[ -f ".3a/roadmap.md" ] && HAS_ROADMAP=true

# --- agentcore create ---
if echo "$COMMAND" | grep -qE 'agentcore\s+create'; then
  if [ "$HAS_3A" = false ]; then
    echo "[3A] 프로젝트를 생성하기 전에 /3a-plan 으로 요구사항과 아키텍처를 먼저 정리하면 좋습니다. 계획 없이 진행할까요, 아니면 먼저 계획을 세울까요?"
  else
    echo "[3A] .3a/ 계획이 이미 존재합니다. 로드맵에 따라 프로젝트를 생성합니다."
  fi
  exit 0
fi

# --- agentcore deploy ---
if echo "$COMMAND" | grep -qE 'agentcore\s+(deploy|dp)'; then
  if [ "$HAS_3A" = true ] && [ -f ".3a/reviews/pre-deploy.md" ]; then
    echo "[3A] 배포 전 리뷰가 완료된 상태입니다. 배포를 진행합니다."
    exit 0
  elif [ "$HAS_3A" = true ]; then
    echo "[3A] 배포 전 리뷰(/3a-review pre-deploy)가 아직 실행되지 않았습니다. 리뷰를 먼저 실행할까요, 아니면 바로 배포할까요?" >&2
    exit 2
  fi
  exit 0
fi

# --- agentcore add ---
if echo "$COMMAND" | grep -qE 'agentcore\s+add'; then
  RESOURCE=$(echo "$COMMAND" | sed -E 's/.*agentcore\s+add\s+([a-zA-Z-]+).*/\1/')
  echo "[3A] '${RESOURCE}' 리소스를 추가하려고 합니다. 추가 후 /3a-decide 로 이 결정을 ADR에 기록하는 것을 권장합니다."
  exit 0
fi

# --- agentcore dev ---
if echo "$COMMAND" | grep -qE 'agentcore\s+dev'; then
  if [ "$HAS_ROADMAP" = true ]; then
    echo "[3A] 로컬 개발 서버를 시작합니다. 테스트 후 /3a-status 로 진행 상황을 업데이트하세요."
  fi
  exit 0
fi

# --- agentcore invoke ---
if echo "$COMMAND" | grep -qE 'agentcore\s+invoke'; then
  echo "[3A] 에이전트를 호출합니다. 결과가 기대와 다르면 /3a-status 로 현재 단계를 확인하세요."
  exit 0
fi

# --- agentcore destroy / delete ---
if echo "$COMMAND" | grep -qE 'agentcore\s+(destroy|delete)'; then
  echo "[3A] 리소스를 삭제하려고 합니다. 이 작업은 되돌리기 어렵습니다. 정말 진행할까요?" >&2
  exit 2
fi

# --- other agentcore commands (status, logs, validate, etc.) ---
exit 0

#!/bin/bash

# Check if .3a directory exists (active project)
if [ -d ".3a" ]; then
  echo "=== 3A (Agentic AI Acceleration) ==="
  echo ""

  # Show roadmap progress if available
  if [ -f ".3a/roadmap.md" ]; then
    TOTAL=$(grep -c '^\- \[' .3a/roadmap.md 2>/dev/null || echo "0")
    DONE=$(grep -c '^\- \[x\]' .3a/roadmap.md 2>/dev/null || echo "0")
    echo "로드맵: ${DONE}/${TOTAL} 작업 완료"

    # Detect current phase
    CURRENT_PHASE=$(grep -B1 '^\- \[ \]' .3a/roadmap.md 2>/dev/null | grep -m1 '^## Phase' | sed 's/^## //')
    if [ -n "$CURRENT_PHASE" ]; then
      echo "현재 단계: ${CURRENT_PHASE}"
    fi
  fi

  # Count ADRs
  if [ -d ".3a/decisions" ]; then
    ADR_COUNT=$(find .3a/decisions -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
    echo "의사결정: ${ADR_COUNT}건 기록됨"
  fi

  # Check for reviews
  if [ -d ".3a/reviews" ]; then
    LATEST_REVIEW=$(ls -t .3a/reviews/*.md 2>/dev/null | head -1)
    if [ -n "$LATEST_REVIEW" ]; then
      REVIEW_NAME=$(basename "$LATEST_REVIEW" .md)
      echo "최근 리뷰: ${REVIEW_NAME}"
    fi
  fi

  echo ""
  echo "자세한 진행 상황은 /3a-status, 로드맵 수정은 /3a-plan 을 사용하세요."

else
  echo "=== 3A (Agentic AI Acceleration) ==="
  echo ""
  echo "안녕하세요! 3A는 AWS 기반 AI 에이전트 프로젝트의 기획, 추적, 검증을 도와드립니다."
  echo ""
  echo "사용 가능한 명령어:"
  echo "- /3a-plan    요구사항 수집, 아키텍처 설계, 실행 로드맵 생성"
  echo "- /3a-status  진행 상황 확인 및 다음 단계 안내"
  echo "- /3a-review  배포·프로덕션 전환 전 준비 상태 검증"
  echo "- /3a-decide  아키텍처 의사결정 기록 (ADR)"
  echo ""
  echo "3A는 기획과 추적에 집중하며, 구현은 aws-agents 플러그인에 위임합니다."
  echo ""
  echo "시작할 준비가 되셨다면 /3a-plan 을 실행하세요."
fi

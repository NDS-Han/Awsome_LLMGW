# AWS Prescriptive Guidance — Agentic AI 시리즈

AWS가 제공하는 에이전트 AI 관련 처방적 가이드 모음입니다. 개발자의 현재 상황에 맞는 가이드를 안내하세요.

## 사용법

개발자가 특정 주제에 대해 질문하면, 아래 카탈로그에서 관련 가이드를 찾아 링크와 함께 "이런 상황이면 이 가이드가 도움이 됩니다"라고 안내합니다. 콘텐츠를 요약하거나 복제하지 말고, 가이드를 직접 읽도록 연결하세요.

---

## 설계 & 구현

에이전트를 설계하고 만드는 과정에서 참고할 가이드입니다.

### Agentic AI Patterns and Workflows

> **"어떤 에이전트 패턴을 써야 하지?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/
- **내용**: 11가지 에이전트 패턴(RAG 에이전트, 도구 기반 에이전트, 메모리 에이전트, 멀티 에이전트 등), LLM 워크플로(프롬프트 체이닝, 라우팅, 병렬화), 프로덕션 아키텍처 패턴(saga, scatter-gather, dynamic dispatch)
- **AWS 서비스 매핑**: 각 패턴별로 Bedrock, Lambda, Step Functions, EventBridge 등 구체적 서비스 연결
- **언제 참고하나**:
  - `3a-plan`에서 에이전트 아키텍처를 설계할 때
  - `3a-guide`에서 멀티 에이전트 패턴 논의 시 더 깊은 근거가 필요할 때
  - 에이전트에 메모리, 도구, 워크플로를 추가하는 방식을 고민할 때

### Agentic AI Frameworks, Platforms, Protocols, and Tools

> **"어떤 프레임워크와 프로토콜을 선택해야 하지?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-frameworks/
- **내용**: 5개 프레임워크 비교(Strands, LangGraph, CrewAI, AutoGen, LlamaIndex — 8개 차원 비교표 포함), 플랫폼 선택(Bedrock Agents, AgentCore), 프로토콜(MCP, A2A) 선택 가이드와 도입 전략, 도구 통합 보안
- **언제 참고하나**:
  - `3a-plan` Step 2에서 프레임워크를 결정할 때
  - MCP와 A2A 중 어떤 프로토콜을 쓸지 고민할 때
  - 프레임워크 전환이나 비교 평가가 필요할 때

### Security for Agentic AI

> **"에이전트 보안은 어떻게 챙기지?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-security/introduction.html
- **내용**: 8개 보안 도메인(시스템 설계, 보안 개발, 평가, 입력 검증/가드레일, 데이터 보안, 인프라, 위협 탐지, 인시던트 대응), OWASP Top 10 for LLM 매핑, AI-specific vs General 통제 구분
- **AWS 서비스**: Bedrock Guardrails, Cognito, WAF, CloudWatch, X-Ray 등 구체적 통제 수단
- **언제 참고하나**:
  - `3a-review` pre-production 검증 시 보안 항목의 근거로
  - 가드레일, 입력 검증, 접근 제어를 설계할 때
  - 보안 위협 모델링이 필요할 때

---

## 인프라 & 운영

배포 이후 인프라와 운영을 고도화할 때 참고할 가이드입니다.

### Building Serverless Architectures for Agentic AI

> **"서버리스로 에이전트를 운영하려면?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-serverless/
- **내용**: 서버리스 비즈니스 케이스, 이벤트 기반 아키텍처(EDA), 오케스트레이션 모델(규칙 기반 vs AI-native), CI/CD 파이프라인(프롬프트 버전 관리 포함), 비용 최적화 전략(모델 계층화, 프롬프트 트리밍, 이벤트 배칭)
- **언제 참고하나**:
  - 배포 후 CI/CD 파이프라인을 구축할 때
  - 운영 비용을 최적화하고 싶을 때
  - Step Functions vs Bedrock Agents 오케스트레이션을 비교할 때

### Operationalizing Agentic AI

> **"에이전트를 조직 차원에서 운영하려면?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/strategy-operationalizing-agentic-ai/
- **내용**: 6개 중점 영역 — 에이전트 의도와 범위 명확화, 조합성과 협업(MCP/A2A), 멀티테넌시와 통제, 신뢰(ID/가드레일/관찰성), 라이프사이클 관리(AgentOps CI/CD), 비즈니스 모델 정렬(수익화, ROI 측정)
- **언제 참고하나**:
  - 에이전트를 팀/조직 차원으로 확장할 때
  - AgentOps(에이전트 운영) 체계를 수립할 때
  - 에이전트 성숙도 모델이 필요할 때

---

## 의사결정 & 거버넌스

전략적 의사결정, 투자 정당화, 조직 거버넌스에 관한 가이드입니다.

### Economics for Agentic AI

> **"에이전트 도입의 ROI를 어떻게 계산하지?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-economics/introduction.html
- **내용**: 3단계 의사결정 프레임워크(업무 평가, 리스크 평가, ROI 분석), 5가지 비용 기준선 수립법, 성과 기반 가격 모델, 채용 운영 사례 연구(월별 손익 분기점 계산 포함)
- **언제 참고하나**:
  - 에이전트 도입을 경영진에게 제안할 때
  - 사람 vs 에이전트 비용 비교가 필요할 때
  - 에이전트 서비스의 가격 모델을 설계할 때

### Governing and Architecting the Diversity of Agentic AI at Scale

> **"조직 내 여러 에이전트를 어떻게 관리하지?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/govern-architect-agentic-ai/introduction.html
- **내용**: 에이전트 유형 분류(챗봇~자율 에이전트), 거버넌스 모델 3종(중앙집중/연합/하이브리드), 엔터프라이즈 참조 아키텍처(애플리케이션·에이전트·코어 서비스 레이어), 에이전트/도구/MCP 레지스트리 관리
- **언제 참고하나**:
  - 조직 내 에이전트 거버넌스 체계를 수립할 때
  - 에이전트 레지스트리와 승인 워크플로를 설계할 때
  - Shadow AI를 방지하는 정책이 필요할 때

---

## 기초 지식 & 특수 아키텍처

배경 지식을 쌓거나 특수한 아키텍처 요구사항이 있을 때 참고할 가이드입니다.

### Foundations of Agentic AI

> **"에이전트 AI의 이론적 배경이 궁금하다"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-foundations/
- **내용**: 소프트웨어 에이전트의 역사(1960년대~현재), Nwana 에이전트 유형론, 3대 원칙(자율성, 비동기성, 에이전시), 인지 사이클(인지-추론-행동), 전통 AI vs 소프트웨어 에이전트 vs 에이전트 AI 비교
- **언제 참고하나**:
  - 에이전트 AI가 무엇인지 개념부터 이해하고 싶을 때
  - 다른 가이드를 읽기 전 기초를 다지고 싶을 때
  - 에이전트 AI의 핵심 구성 요소(인지, 행동, 학습 모듈)를 이해하고 싶을 때

### Building Multi-Tenant Architectures for Agentic AI

> **"SaaS로 에이전트를 제공하려면?"**

- **URL**: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-multitenant/
- **내용**: 3가지 배포 모델(사일로/풀/하이브리드), 테넌트 격리 전략, 에이전트 라우팅 구조, 온보딩·리소스 관리·모니터링
- **언제 참고하나**:
  - 에이전트를 SaaS 형태로 여러 고객에게 제공할 때
  - 테넌트 간 격리와 노이지 네이버 방지가 필요할 때
  - 에이전트 배포 모델(사일로 vs 풀)을 결정할 때

---

## 빠른 찾기

| 질문 | 가이드 |
|---|---|
| 어떤 에이전트 패턴을 쓸까? | Patterns and Workflows |
| 프레임워크를 뭘로 할까? | Frameworks |
| MCP vs A2A 어떤 걸 쓸까? | Frameworks |
| 보안은 어떻게 챙기지? | Security |
| CI/CD를 어떻게 구축하지? | Serverless |
| 비용을 줄이려면? | Serverless, Economics |
| ROI를 어떻게 보여주지? | Economics |
| 조직 거버넌스는? | Govern & Architect |
| 에이전트 AI가 뭐야? | Foundations |
| SaaS 멀티테넌트로 만들려면? | Multitenant |
| 조직에서 에이전트를 확장하려면? | Operationalizing |

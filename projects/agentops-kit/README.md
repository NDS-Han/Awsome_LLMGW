# AgentOps Kit

AWS Seoul Summit 2026 데모 — **프로덕션으로 가기 위한 Agentic AI 아키텍처 설계하기**

이커머스 데이터 분석 에이전트로 AgentOps 파이프라인 전반을 시연:
**Gateway → Observability → Evaluation → Improvement**

## Quick Start

```bash
# 1. 저장소 & 의존성
git clone <repository-url> agentops-kit
cd agentops-kit
pip install -r requirements.txt
(cd frontend && npm install)

# 2. Olist CSV를 _data/ 에 배치

# 3. Aurora + Lambda 배포
bash infra/deploy.sh deploy
bash infra/deploy.sh env
bash infra/deploy.sh lambda

# 4. CSV → Aurora 적재
python data/migrate.py

# 5. AgentCore Gateway 생성 + 도구 등록
python infra/setup_gateway.py

# 6. AgentCore Runtime 배포
agentcore deploy --env ...  (자세한 내용은 DEMO_GUIDE.md 참조)

# 7. 데모 시작
make demo-start
```

상세 가이드: [DEMO_GUIDE.md](./DEMO_GUIDE.md)

## Architecture

```
User → React Dashboard (3000) → FastAPI (8000)
                                     │
                                     ▼  boto3.invoke_agent_runtime
                           AgentCore Runtime (컨테이너, ARM64)
                                     │
                                     ▼  Strands Agent + MCP
                           AgentCore Gateway (OAuth + Semantic Search)
                                     │
                                     ▼  Lambda target
                           tool-router Lambda
                                     │
                                     ▼  RDS Data API (HTTPS)
                           Aurora PostgreSQL Serverless v2
                           (Private, Data API only)

관측성: AgentCore Observability → CloudWatch GenAI Observability
평가:   AgentCore Evaluations (Helpfulness / Correctness / GoalSuccessRate)
모델:   Bedrock Claude Sonnet 4.6 (global inference profile)
```

## Tech Stack

- **AgentCore** Runtime / Gateway / Observability / Evaluation
- **Strands Agents** (MCP client) + **Amazon Bedrock** (Claude Sonnet 4.6)
- **Aurora PostgreSQL Serverless v2** (RDS Data API, private)
- **FastAPI** (BFF) + **React** + **Recharts** (AWS 콘솔 스타일)
- **Olist Brazilian E-commerce Dataset**

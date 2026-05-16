# AgentOps Kit

AWS Seoul Summit 2026 demo — **Designing Agentic AI Architectures for Production** (AIM310)

An e-commerce data-analytics agent that demonstrates the full AgentOps pipeline:
**Gateway → Observability → Evaluation → Improvement**

## Quick Start

```bash
# 1. Clone & install dependencies
git clone <repository-url> agentops-kit
cd agentops-kit
pip install -r requirements.txt
(cd frontend && npm install)

# 2. Place the Olist CSV dataset under _data/

# 3. Deploy Aurora + Lambda
bash infra/deploy.sh deploy
bash infra/deploy.sh env
bash infra/deploy.sh lambda

# 4. Load CSV into Aurora
python data/migrate.py

# 5. Create the AgentCore Gateway and register tools
python infra/setup_gateway.py

# 6. Deploy the AgentCore Runtime
agentcore deploy --env ...  (see DEMO_GUIDE.md for details)

# 7. Start the demo
make demo-start
```

For the full walkthrough, see [DEMO_GUIDE.md](./DEMO_GUIDE.md).

## Architecture

```
User → React Dashboard (3000) → FastAPI (8000)
                                     │
                                     ▼  boto3.invoke_agent_runtime
                           AgentCore Runtime (container, ARM64)
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

Observability: AgentCore Observability → CloudWatch GenAI Observability
Evaluation:    AgentCore Evaluations (Helpfulness / Correctness / GoalSuccessRate)
Model:         Bedrock Claude Sonnet 4.6 (global inference profile)
```

## Tech Stack

- **AgentCore** Runtime / Gateway / Observability / Evaluation
- **Strands Agents** (MCP client) + **Amazon Bedrock** (Claude Sonnet 4.6)
- **Aurora PostgreSQL Serverless v2** (RDS Data API, private)
- **FastAPI** (BFF) + **React** + **Recharts** (AWS console style)
- **Olist Brazilian E-commerce Dataset**

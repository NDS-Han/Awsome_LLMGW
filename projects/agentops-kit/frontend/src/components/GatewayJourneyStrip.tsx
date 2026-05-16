import { useEffect, useState } from "react";
import { Cpu, Wrench, Users } from "lucide-react";
import { api } from "../api";
import { GatewayJourneyState, LLMGatewayState } from "../types";

/**
 * Chat 탭 상단의 1-line 'Gateway Journey' 스트립.
 * 질문 1건이 LLM → Tool → Agent 세 관문을 어떻게 통과했는지 한 줄로 보여준다.
 * Gateway 5분 데모의 내러티브 앵커.
 */
export default function GatewayJourneyStrip() {
  const [journey, setJourney] = useState<GatewayJourneyState | null>(null);
  const [llm, setLlm] = useState<LLMGatewayState | null>(null);

  useEffect(() => {
    const load = () => {
      api.getGatewayJourney().then(setJourney).catch(() => {});
      api.getLLMGateway().then(setLlm).catch(() => {});
    };
    load();
    const iv = setInterval(load, 2000);
    return () => clearInterval(iv);
  }, []);

  const modelShort = (id: string) =>
    id ? id.split(".").slice(-1)[0] : "—";

  const llmActive = !!(journey?.active && (journey.llm.model || llm?.last_model_used));
  const toolActive = !!(journey?.active && journey.tool.last);
  const agentActive = !!(journey?.active && journey.agent.handoff);

  const modelLabel = journey?.llm.model || llm?.last_model_used || "";
  const routingReason = llm?.last_routing_reason || "";
  const toolLabel = journey?.tool.last || "—";
  const agentLabel = journey?.agent.handoff
    ? `main → ${journey?.agent.target || "specialist"}`
    : "핸드오프 없음";

  const cost = journey?.summary.cost_usd || 0;
  const tokens = journey?.summary.total_tokens || 0;
  const duration = journey?.summary.duration_ms || 0;

  return (
    <div className="journey-strip">
      <span style={{fontSize:10,color:"var(--gray-600)",textTransform:"uppercase",letterSpacing:0.5,marginRight:4}}>
        Gateway Journey
      </span>

      <span className={`journey-step ${llmActive ? "active-llm" : ""}`}>
        <Cpu size={12}/>
        <span className="dot"/>
        <span style={{fontFamily:"'JetBrains Mono',monospace"}}>LLM</span>
        <span style={{color:"var(--gray-400)"}}>: {modelShort(modelLabel) || "—"}</span>
      </span>

      <span className="journey-arrow">→</span>

      <span className={`journey-step ${toolActive ? "active-tool" : ""}`}>
        <Wrench size={12}/>
        <span className="dot"/>
        <span style={{fontFamily:"'JetBrains Mono',monospace"}}>Tool</span>
        <span style={{color:"var(--gray-400)"}}>: {toolLabel}</span>
      </span>

      <span className="journey-arrow">→</span>

      <span className={`journey-step ${agentActive ? "active-agent" : ""}`}>
        <Users size={12}/>
        <span className="dot"/>
        <span style={{fontFamily:"'JetBrains Mono',monospace"}}>Agent</span>
        <span style={{color:"var(--gray-400)"}}>: {agentLabel}</span>
      </span>

      <div className="journey-summary">
        {routingReason && <span title={routingReason}>⚡ {routingReason}</span>}
        <span>${cost.toFixed(5)}</span>
        <span>{tokens.toLocaleString()} 토큰</span>
        <span>{duration}ms</span>
      </div>
    </div>
  );
}

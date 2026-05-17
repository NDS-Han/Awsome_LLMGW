import { useState, useRef, useEffect } from "react";
import { MessageSquare, Send, Clock, Wrench, Coins, ShieldCheck, ShieldX, Eye, Loader2 } from "lucide-react";
import { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  onSend: (prompt: string) => void;
  loading: boolean;
  compact?: boolean;
}

const EXAMPLE_PROMPTS = [
  "2017년 매출 기준 상위 5개 상품 카테고리는?",
  "고객 리뷰 만족도 트렌드를 분석해줘",
  "주(state)별 배송 성과는 어떻게 되나요?",
  "매출 기준 상위 10개 셀러를 보여줘",
];

export default function ChatPanel({ messages, onSend, loading, compact }: Props) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    onSend(input.trim());
    setInput("");
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <MessageSquare size={14} />
          에이전트 채팅
        </div>
        {messages.length > 0 && (
          <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
            {messages.length}개 메시지
          </span>
        )}
      </div>

      <div className="panel-body">
        {messages.length === 0 ? (
          <div className="empty-state">
            <MessageSquare size={40} />
            <p>이커머스 데이터에 대해 질문해보세요</p>
            <p className="empty-hint">아래 예시 질문을 클릭하거나 직접 입력하세요</p>
            {!compact && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8, justifyContent: "center" }}>
                {EXAMPLE_PROMPTS.map((p) => (
                  <button
                    key={p}
                    className="btn btn-secondary btn-sm"
                    onClick={() => onSend(p)}
                    disabled={loading}
                  >
                    {p.length > 40 ? p.slice(0, 40) + "..." : p}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="chat-messages">
            {messages.map((msg, i) => (
              <div key={i} className={`chat-msg ${msg.role}`}>
                {msg.content}
                {msg.role === "assistant" && msg.trace_id && (
                  <div className="chat-meta">
                    {msg.latency_ms && <span className="badge badge--neutral"><Clock size={9} /> {msg.latency_ms}ms</span>}
                    {msg.tools_used?.map((t) => (
                      <span key={t} className="badge badge--info"><Wrench size={9} /> {t}</span>
                    ))}
                    {msg.token_usage && (
                      <span className="badge badge--neutral badge--mono">{msg.token_usage.total_tokens} 토큰</span>
                    )}
                    {msg.cost && (
                      <span className="badge badge--warning"><Coins size={9} /> ${msg.cost.total_cost.toFixed(5)}</span>
                    )}
                    {msg.guardrails && (
                      <span className={`badge ${msg.guardrails.passed ? "badge--success" : "badge--danger"}`}>
                        {msg.guardrails.passed ? <ShieldCheck size={9} /> : <ShieldX size={9} />}
                        가드레일{msg.guardrails.violations.length > 0 && ` (${msg.guardrails.violations.length}건)`}
                      </span>
                    )}
                    {msg.redacted && (
                      <span className="badge badge--warning"><Eye size={9} /> PII 마스킹</span>
                    )}
                    {msg.evalLoading && (
                      <span className="badge badge--neutral"><Loader2 size={9} className="spin" /> 평가 중</span>
                    )}
                    {msg.eval && (
                      <span className={`badge ${msg.eval.avg_score >= 0.8 ? "badge--success" : msg.eval.avg_score >= 0.6 ? "badge--warning" : "badge--danger"}`}>
                        평가: {(msg.eval.avg_score * 100).toFixed(0)}% {msg.eval.label}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="chat-msg assistant">
                <span className="loading-dots">
                  <span /><span /><span />
                </span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="chat-input-row">
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="매출, 리뷰, 배송, 셀러에 대해 무엇이든 물어보세요…"
          disabled={loading}
        />
        <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()}>
          <Send size={14} />
        </button>
      </form>
    </div>
  );
}

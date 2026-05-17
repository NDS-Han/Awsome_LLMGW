import { useState, useEffect } from "react";
import { ShieldCheck, ShieldAlert, ShieldX, AlertTriangle, Lightbulb, CheckCircle2 } from "lucide-react";
import { api } from "../api";
import { GuardrailResult } from "../types";

interface Props {
  latestGuardrail: GuardrailResult | null;
  compact?: boolean;
}

const SEVERITY_ICON = {
  critical: <ShieldX size={12} style={{ color: "var(--red-light)" }} />,
  warn: <ShieldAlert size={12} style={{ color: "var(--amber)" }} />,
  info: <AlertTriangle size={12} style={{ color: "var(--gray-400)" }} />,
};

const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--red-light)",
  warn: "var(--amber)",
  info: "var(--gray-400)",
};

export default function GuardrailsPanel({ latestGuardrail, compact }: Props) {
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<GuardrailResult | null>(null);
  const [testing, setTesting] = useState(false);

  const runTest = async () => {
    if (!testText.trim()) return;
    setTesting(true);
    try {
      const result = await api.testGuardrails(testText);
      setTestResult(result);
    } finally {
      setTesting(false);
    }
  };

  const current = testResult || latestGuardrail;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <ShieldCheck size={14} />
          가드레일
        </div>
        {current && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: current.passed ? "var(--green-light)" : "var(--red-light)",
            }}
          >
            {current.passed ? "통과" : "실패"}
          </span>
        )}
      </div>

      <div className="panel-body">
        {!current ? (
          <div className="empty-state">
            <ShieldCheck size={40} />
            <p>아직 검사된 가드레일이 없습니다</p>
            <p className="empty-hint">채팅 응답이 생성되면 가드레일이 자동으로 실행됩니다</p>
          </div>
        ) : (
          <>
            {/* Summary */}
            <div className="metrics-grid" style={{ marginBottom: 10 }}>
              <div className="metric-card metric-card--red">
                <div className="metric-label">심각</div>
                <div className="metric-value" style={{ color: "var(--red-light)" }}>
                  {current.critical_count}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">경고</div>
                <div className="metric-value" style={{ color: "var(--amber)" }}>
                  {current.warn_count}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">정보</div>
                <div className="metric-value" style={{ color: "var(--gray-400)" }}>
                  {current.info_count}
                </div>
              </div>
            </div>

            {/* Checks Run */}
            <div style={{ marginBottom: 10, display: "flex", flexWrap: "wrap", gap: 4 }}>
              {(current.checks_run ?? []).map((c) => (
                <span key={c} className="badge badge--success badge--mono">
                  <CheckCircle2 size={9} /> {c}
                </span>
              ))}
            </div>

            {/* Violations */}
            {(current.violations?.length ?? 0) > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div className="section-block__title">
                  <AlertTriangle size={11} />
                  <span>위반 사항</span>
                  <span className="badge badge--danger">{current.violations.length}건</span>
                </div>
                {current.violations.slice(0, compact ? 3 : 20).map((v, i) => (
                  <div
                    key={i}
                    style={{
                      padding: 8,
                      background: "var(--navy-darkest)",
                      border: `1px solid ${SEVERITY_COLOR[v.severity]}40`,
                      borderLeft: `3px solid ${SEVERITY_COLOR[v.severity]}`,
                      borderRadius: "var(--radius)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                      {SEVERITY_ICON[v.severity]}
                      <span className="badge badge--mono" style={{ background: `${SEVERITY_COLOR[v.severity]}15`, color: SEVERITY_COLOR[v.severity], border: `1px solid ${SEVERITY_COLOR[v.severity]}40` }}>
                        {v.rule_id}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--gray-300)", marginTop: 4 }}>{v.message}</div>
                    {v.matched_text && (
                      <div
                        style={{
                          fontSize: 10,
                          marginTop: 4,
                          padding: "2px 6px",
                          background: "var(--navy)",
                          borderRadius: 3,
                          fontFamily: "'JetBrains Mono', monospace",
                          color: "var(--gray-400)",
                        }}
                      >
                        "{v.matched_text}"
                      </div>
                    )}
                    {v.suggestion && !compact && (
                      <div
                        style={{
                          fontSize: 10,
                          marginTop: 4,
                          color: "var(--gray-500)",
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <Lightbulb size={9} /> {v.suggestion}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div
                style={{
                  padding: 12,
                  background: "rgba(106, 175, 53, 0.1)",
                  border: "1px solid rgba(106, 175, 53, 0.3)",
                  borderRadius: "var(--radius)",
                  fontSize: 11,
                  color: "var(--green-light)",
                  textAlign: "center",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                }}
              >
                <CheckCircle2 size={13} /> 모든 가드레일 검사를 통과했습니다
              </div>
            )}

            {/* Test Input (non-compact only) */}
            {!compact && (
              <div style={{ marginTop: 14, borderTop: "1px solid var(--navy-light)", paddingTop: 10 }}>
                <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>
                  가드레일 테스트
                </div>
                <textarea
                  value={testText}
                  onChange={(e) => setTestText(e.target.value)}
                  placeholder="검사할 텍스트를 붙여넣으세요 (예: PII가 포함된 응답, 잘못된 카테고리 등)…"
                  className="chat-input"
                  style={{ width: "100%", minHeight: 60, resize: "vertical", marginBottom: 6 }}
                />
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={runTest}
                  disabled={testing || !testText.trim()}
                >
                  {testing ? "검사 중…" : "가드레일 실행"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

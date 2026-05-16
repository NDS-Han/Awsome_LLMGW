import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api } from "../api";
import { AnomalyAlarm } from "../types";

const STATE_COLORS: Record<string, string> = {
  OK: "#22c55e",
  ALARM: "#ef4444",
  INSUFFICIENT_DATA: "#6b7280",
};

function AlarmCard({ alarm }: { alarm: AnomalyAlarm }) {
  const color = STATE_COLORS[alarm.state] || "#6b7280";
  const pct =
    alarm.expected_high > alarm.expected_low
      ? ((alarm.current_value - alarm.expected_low) /
          (alarm.expected_high - alarm.expected_low)) *
        100
      : 50;

  return (
    <div
      className="metric-card"
      style={{ borderLeft: `3px solid ${color}`, marginBottom: 8 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-200)" }}>
          {alarm.display_name}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color,
            padding: "1px 6px",
            borderRadius: 4,
            background: `${color}20`,
          }}
        >
          {alarm.state}
        </span>
      </div>

      {/* Anomaly band bar */}
      <div
        style={{
          position: "relative",
          height: 8,
          background: "var(--bg-tertiary, #1e293b)",
          borderRadius: 4,
          marginBottom: 6,
          overflow: "visible",
        }}
      >
        {/* Expected range */}
        <div
          style={{
            position: "absolute",
            left: "10%",
            right: "10%",
            height: "100%",
            background: `${color}15`,
            borderRadius: 4,
            border: `1px dashed ${color}40`,
          }}
        />
        {/* Current value indicator */}
        <div
          style={{
            position: "absolute",
            left: `${Math.max(2, Math.min(98, pct))}%`,
            top: -2,
            width: 4,
            height: 12,
            background: color,
            borderRadius: 2,
            transform: "translateX(-50%)",
          }}
        />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--gray-500)" }}>
        <span>
          하한: {alarm.expected_low.toFixed(1)} {alarm.unit}
        </span>
        <span style={{ fontWeight: 600, color: "var(--gray-300)" }}>
          현재: {alarm.current_value.toFixed(1)} {alarm.unit}
        </span>
        <span>
          상한: {alarm.expected_high.toFixed(1)} {alarm.unit}
        </span>
      </div>
    </div>
  );
}

export default function AnomalyPanel({ compact }: { compact?: boolean }) {
  const [alarms, setAlarms] = useState<AnomalyAlarm[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .getAnomalies()
        .then((res) => setAlarms(res.alarms || []))
        .catch((e) => setError(e.message));
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);

  const alarmCount = alarms.filter((a) => a.state === "ALARM").length;

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><AlertTriangle size={14} />이상 탐지</div>
          <span style={{ fontSize: 11, color: alarmCount > 0 ? "#ef4444" : "var(--gray-500)" }}>
            {alarmCount > 0 ? `알람 ${alarmCount}건` : "정상"}
          </span>
        </div>
        <div className="panel-body">
          {alarms.length === 0 ? (
            <div className="empty-state"><AlertTriangle size={32} /><p>알람이 없습니다</p></div>
          ) : alarms.slice(0, 3).map((alarm) => (
            <AlarmCard key={alarm.metric_name} alarm={alarm} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <AlertTriangle size={14} />
          이상 탐지
        </div>
        <span style={{ fontSize: 11, color: alarmCount > 0 ? "#ef4444" : "var(--gray-500)" }}>
          {alarmCount > 0 ? `알람 ${alarmCount}건 활성` : "모두 정상"}
        </span>
      </div>
      <div className="panel-body">
        {error ? (
          <div className="empty-state">
            <AlertTriangle size={40} />
            <p>이상 탐지 데이터를 불러올 수 없습니다</p>
            <p className="empty-hint">{error}</p>
          </div>
        ) : alarms.length === 0 ? (
          <div className="empty-state">
            <AlertTriangle size={40} />
            <p>설정된 이상 탐지 알람이 없습니다</p>
            <p className="empty-hint">CloudWatch Anomaly Detection 알람을 구성해주세요</p>
          </div>
        ) : (
          alarms.map((alarm) => (
            <AlarmCard key={alarm.metric_name} alarm={alarm} />
          ))
        )}
      </div>
    </div>
  );
}

import { useState, FormEvent } from "react";
import { signIn } from "../auth";

interface Props {
  onSuccess: () => void;
}

export default function LoginForm({ onSuccess }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const ok = await signIn(email, password);
      if (ok) {
        onSuccess();
      } else {
        setError("Login failed. Please try again.");
      }
    } catch (err: any) {
      const msg = err?.message || "Authentication failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: "100vh", background: "var(--bg-primary, #0a0a0f)",
    }}>
      <form onSubmit={handleSubmit} style={{
        background: "var(--bg-secondary, #1a1a2e)", borderRadius: 12,
        padding: 32, width: 360, boxShadow: "0 4px 24px rgba(0,0,0,0.4)",
      }}>
        <h2 style={{ color: "var(--gray-100, #f0f0f0)", marginBottom: 24, textAlign: "center" }}>
          AgentOps Login
        </h2>

        {error && (
          <div style={{
            background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
            borderRadius: 8, padding: "8px 12px", marginBottom: 16,
            color: "#f87171", fontSize: 13,
          }}>
            {error}
          </div>
        )}

        <label style={{ display: "block", marginBottom: 12 }}>
          <span style={{ color: "var(--gray-400, #999)", fontSize: 12, display: "block", marginBottom: 4 }}>Email</span>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            autoFocus
            style={{
              width: "100%", padding: "10px 12px", borderRadius: 6,
              border: "1px solid var(--gray-700, #333)", background: "var(--bg-primary, #0a0a0f)",
              color: "var(--gray-100, #f0f0f0)", fontSize: 14, outline: "none",
            }}
            placeholder="alice@demo.local"
          />
        </label>

        <label style={{ display: "block", marginBottom: 20 }}>
          <span style={{ color: "var(--gray-400, #999)", fontSize: 12, display: "block", marginBottom: 4 }}>Password</span>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            style={{
              width: "100%", padding: "10px 12px", borderRadius: 6,
              border: "1px solid var(--gray-700, #333)", background: "var(--bg-primary, #0a0a0f)",
              color: "var(--gray-100, #f0f0f0)", fontSize: 14, outline: "none",
            }}
            placeholder="Demo1234!"
          />
        </label>

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%", padding: "10px 0", borderRadius: 6,
            background: loading ? "#555" : "var(--accent, #6366f1)",
            color: "#fff", fontSize: 14, fontWeight: 600,
            border: "none", cursor: loading ? "wait" : "pointer",
          }}
        >
          {loading ? "Signing in..." : "Sign In"}
        </button>

        <p style={{ color: "var(--gray-500, #666)", fontSize: 11, textAlign: "center", marginTop: 16 }}>
          Test: alice@demo.local / Demo1234!
        </p>
      </form>
    </div>
  );
}

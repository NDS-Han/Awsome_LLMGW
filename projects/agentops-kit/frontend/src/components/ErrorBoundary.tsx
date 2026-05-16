import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: React.ReactNode;
  panelName?: string;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    const tag = this.props.panelName ? `[ErrorBoundary · %s]` : `[ErrorBoundary]`;
    if (this.props.panelName) {
      console.error(tag, this.props.panelName, error, info);
    } else {
      console.error(tag, error, info);
    }
  }

  reset = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title" style={{ color: "var(--red-light)" }}>
            <AlertTriangle size={14} />
            {this.props.panelName || "패널"} 렌더링 오류
          </div>
          <button className="btn btn-secondary btn-sm" onClick={this.reset}>
            <RotateCcw size={10} /> 재시도
          </button>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <AlertTriangle size={40} />
            <p>이 패널을 렌더링할 수 없습니다</p>
            <p className="empty-hint" style={{ fontFamily: "var(--ff-mono)", fontSize: 10, color: "var(--gray-500)" }}>
              {this.state.error.message}
            </p>
          </div>
        </div>
      </div>
    );
  }
}

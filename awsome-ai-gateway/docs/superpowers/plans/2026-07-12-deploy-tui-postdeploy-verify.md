# Deploy TUI 배포 후 검증/안내 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `deploy-tui` 로 LLM Gateway 배포 성공 직후 접속 엔드포인트 + 다음 단계 가이드를 자동 출력하고, 메인 메뉴에 라이브 헬스체크 + smoke-test 를 돌리는 "배포 검증" 항목을 추가한다.

**Architecture:** 순수 조회/판정 로직을 새 모듈 `deployment/tui/postdeploy.py` 에 담고(예외를 던지지 않고 구조화된 dataclass 반환), 렌더링과 진입점 연결은 `cli.py` 가 rich 로 담당한다. kubectl/curl 은 subprocess 로 호출하되 테스트에서 전부 monkeypatch 한다.

**Tech Stack:** Python 3, rich, questionary, pytest. subprocess 로 kubectl/curl 호출. 기존 `runner.run_workflow`/`cli.run_and_report` 재사용(smoke-test 실행용).

## Global Constraints

- 새로운 값 하드코딩 금지. `cluster_name`/`release`/`namespace` 는 파라미터(기본값 `"llm-gateway"`). ALB hostname 은 항상 kubectl 조회.
- `postdeploy.py` 는 어떤 실패에도 예외를 던지지 않는다 — 실패는 결과값(`None`/`error`/`pending`)으로 표현.
- `postdeploy.py` 는 rich 를 import 하지 않는다(렌더링은 cli.py 전담).
- 상태는 3-state 만: `"ok"`(✓) / `"pending"`(⏳) / `"check"`(⚠). 빨간 ✗ 안 씀.
- 테스트는 리포 루트에서 `python -m pytest deployment/tui/tests/ -v`. import 는 `from deployment.tui import ...`. subprocess/네트워크는 전부 monkeypatch.
- ingress 식별은 라벨 셀렉터 `app.kubernetes.io/instance=<release>` + 이름 suffix 매핑(smoke-test.sh 와 일관).
- 격리 KUBECONFIG 경로 규칙: `/tmp/{cluster_name}.kubeconfig` (steps.py 와 동일).

---

## File Structure

| 파일 | 책임 |
|------|------|
| `deployment/tui/postdeploy.py` | **신규** — dataclass(`Endpoint`/`Endpoints`/`HealthResult`) + 상수(`ROLE_SUFFIX`/`HEALTH_PATH`) + 조회/판정 함수(`isolated_kubeconfig`/`discover_endpoints`/`live_healthcheck`) |
| `deployment/tui/cli.py` | 렌더 헬퍼 3개(`render_endpoints_panel`/`render_next_steps`/`render_health_table`) + `flow_llm` 끝 훅 + `flow_verify` 신규 + MENU 항목 |
| `deployment/tui/tests/test_postdeploy.py` | **신규** — postdeploy 순수 로직 단위 테스트 |
| `deployment/tui/tests/test_cli.py` | 렌더 헬퍼 + flow_verify + MENU 테스트 추가 |

---

## Task 1: postdeploy 데이터 구조 + 상수 + 격리 kubeconfig

**Files:**
- Create: `deployment/tui/postdeploy.py`
- Test: `deployment/tui/tests/test_postdeploy.py`

**Interfaces:**
- Produces:
  - `@dataclass Endpoint(role: str, ingress_name: str, hostname: str | None)` + property `url -> str | None` (`"http://<hostname>"` 또는 None)
  - `@dataclass Endpoints(items: list[Endpoint], error: str | None = None)` + method `by_role(role: str) -> Endpoint | None`
  - `@dataclass HealthResult(label: str, state: str, detail: str)` — state ∈ {"ok","pending","check"}
  - `ROLE_SUFFIX: dict[str,str]`, `HEALTH_PATH: dict[str,str]`
  - `isolated_kubeconfig(cluster_name: str = "llm-gateway") -> str`

- [ ] **Step 1: Write the failing test**

`deployment/tui/tests/test_postdeploy.py`:
```python
from deployment.tui import postdeploy as pd


def test_endpoint_url_builds_http_when_hostname_present():
    ep = pd.Endpoint(role="gateway", ingress_name="llm-gateway-gateway", hostname="abc.elb.amazonaws.com")
    assert ep.url == "http://abc.elb.amazonaws.com"


def test_endpoint_url_none_when_hostname_missing():
    ep = pd.Endpoint(role="gateway", ingress_name="llm-gateway-gateway", hostname=None)
    assert ep.url is None


def test_endpoints_by_role_finds_and_misses():
    eps = pd.Endpoints(items=[pd.Endpoint("admin-ui", "llm-gateway-admin-ui", "h")])
    assert eps.by_role("admin-ui").hostname == "h"
    assert eps.by_role("gateway") is None


def test_isolated_kubeconfig_follows_tmp_rule():
    assert pd.isolated_kubeconfig("llm-gateway") == "/tmp/llm-gateway.kubeconfig"
    assert pd.isolated_kubeconfig("other") == "/tmp/other.kubeconfig"


def test_role_maps_cover_three_roles():
    assert set(pd.ROLE_SUFFIX) == {"gateway", "admin-api", "admin-ui"}
    assert pd.HEALTH_PATH["admin-ui"] == "/"
    assert pd.HEALTH_PATH["gateway"] == "/health"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_postdeploy.py -v`
Expected: FAIL — `ModuleNotFoundError: deployment.tui.postdeploy`

- [ ] **Step 3: Write minimal implementation**

`deployment/tui/postdeploy.py`:
```python
# Copyright 2026 © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms.
"""배포 후 검증 — 엔드포인트 조회/헬스체크 순수 로직.

kubectl/curl 을 subprocess 로 호출하되 예외를 던지지 않는다(실패는 결과값으로
표현). rich 를 import 하지 않는다 — 렌더링은 cli.py 전담."""
from __future__ import annotations

from dataclasses import dataclass, field

# role↔ingress 이름 suffix 매핑. helm 차트 구조에서 오는 규칙이라 상수.
# 이름 전체를 박지 않고 라벨 셀렉터로 받은 뒤 suffix 로 role 을 역매핑한다.
ROLE_SUFFIX = {"gateway": "gateway", "admin-api": "admin-api", "admin-ui": "admin-ui"}
# 헬스체크 경로: gateway/admin-api 는 /health, admin-ui(Next.js)는 루트로 307 확인.
HEALTH_PATH = {"gateway": "/health", "admin-api": "/health", "admin-ui": "/"}

ORDER = ("gateway", "admin-api", "admin-ui")


@dataclass
class Endpoint:
    role: str
    ingress_name: str
    hostname: str | None

    @property
    def url(self) -> str | None:
        return f"http://{self.hostname}" if self.hostname else None


@dataclass
class Endpoints:
    items: list[Endpoint] = field(default_factory=list)
    error: str | None = None

    def by_role(self, role: str) -> Endpoint | None:
        return next((e for e in self.items if e.role == role), None)


@dataclass
class HealthResult:
    label: str
    state: str  # "ok" | "pending" | "check"
    detail: str


def isolated_kubeconfig(cluster_name: str = "llm-gateway") -> str:
    """steps.py 와 동일한 격리 KUBECONFIG 경로 규칙."""
    return f"/tmp/{cluster_name}.kubeconfig"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_postdeploy.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/tui/postdeploy.py deployment/tui/tests/test_postdeploy.py
git commit -m "feat(deploy-tui): postdeploy dataclasses + role maps

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: discover_endpoints (kubectl ingress 조회 + 파싱)

**Files:**
- Modify: `deployment/tui/postdeploy.py`
- Test: `deployment/tui/tests/test_postdeploy.py`

**Interfaces:**
- Consumes: `Endpoint`, `Endpoints`, `ROLE_SUFFIX`, `ORDER`, `isolated_kubeconfig` (Task 1)
- Produces: `discover_endpoints(cluster_name="llm-gateway", release="llm-gateway", namespace="llm-gateway") -> Endpoints`
  - 내부적으로 `_run_kubectl(args: list[str], cluster_name: str) -> tuple[int, str]` 헬퍼를 통해 subprocess 호출(테스트가 이 헬퍼를 monkeypatch).

- [ ] **Step 1: Write the failing test**

`test_postdeploy.py` 에 추가:
```python
import json


def _fake_ingress_json(items):
    # items: list of (name, hostname_or_None)
    return json.dumps({
        "items": [
            {
                "metadata": {"name": name},
                "status": {"loadBalancer": {"ingress": ([{"hostname": h}] if h else [])}},
            }
            for name, h in items
        ]
    })


def test_discover_endpoints_parses_three(monkeypatch):
    payload = _fake_ingress_json([
        ("llm-gateway-gateway", "g.elb.amazonaws.com"),
        ("llm-gateway-admin-api", "a.elb.amazonaws.com"),
        ("llm-gateway-admin-ui", "u.elb.amazonaws.com"),
    ])
    monkeypatch.setattr(pd, "_run_kubectl", lambda args, cluster_name: (0, payload))
    eps = pd.discover_endpoints()
    assert eps.error is None
    assert eps.by_role("gateway").url == "http://g.elb.amazonaws.com"
    assert eps.by_role("admin-ui").hostname == "u.elb.amazonaws.com"


def test_discover_endpoints_hostname_pending_is_none(monkeypatch):
    payload = _fake_ingress_json([("llm-gateway-gateway", None)])
    monkeypatch.setattr(pd, "_run_kubectl", lambda args, cluster_name: (0, payload))
    eps = pd.discover_endpoints()
    assert eps.by_role("gateway").hostname is None
    assert eps.by_role("gateway").url is None


def test_discover_endpoints_kubectl_failure_sets_error(monkeypatch):
    monkeypatch.setattr(pd, "_run_kubectl", lambda args, cluster_name: (1, "error: cluster unreachable"))
    eps = pd.discover_endpoints()
    assert eps.items == []
    assert eps.error is not None


def test_discover_endpoints_bad_json_sets_error(monkeypatch):
    monkeypatch.setattr(pd, "_run_kubectl", lambda args, cluster_name: (0, "not json"))
    eps = pd.discover_endpoints()
    assert eps.error is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_postdeploy.py -k discover -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_run_kubectl'` / `discover_endpoints`

- [ ] **Step 3: Write minimal implementation**

`postdeploy.py` 상단 import 에 추가:
```python
import json
import os
import subprocess
```

`postdeploy.py` 에 함수 추가:
```python
def _run_kubectl(args: list[str], cluster_name: str) -> tuple[int, str]:
    """격리 KUBECONFIG 로 kubectl 실행. (returncode, stdout+stderr) 반환.
    예외를 던지지 않는다 — 미설치/타임아웃도 (비정상코드, 메시지)로."""
    env = dict(os.environ)
    env["KUBECONFIG"] = isolated_kubeconfig(cluster_name)
    try:
        proc = subprocess.run(
            ["kubectl", *args],
            capture_output=True, text=True, env=env, timeout=15,
        )
    except FileNotFoundError:
        return 127, "kubectl not found"
    except subprocess.TimeoutExpired:
        return 124, "kubectl timed out"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _role_for(name: str) -> str | None:
    """ingress 이름 suffix 로 role 역매핑. 긴 suffix 우선(admin-api/admin-ui가
    gateway보다 먼저 매칭되도록 정렬)."""
    for role in sorted(ROLE_SUFFIX, key=lambda r: -len(ROLE_SUFFIX[r])):
        if name.endswith(ROLE_SUFFIX[role]):
            return role
    return None


def discover_endpoints(cluster_name: str = "llm-gateway",
                       release: str = "llm-gateway",
                       namespace: str = "llm-gateway") -> Endpoints:
    """라벨 셀렉터로 ingress 3개를 조회해 role/hostname 매핑. 실패해도 예외 없이
    Endpoints(error=...) 반환."""
    rc, out = _run_kubectl(
        ["get", "ingress", "-n", namespace,
         "-l", f"app.kubernetes.io/instance={release}", "-o", "json"],
        cluster_name,
    )
    if rc != 0:
        return Endpoints(items=[], error=out.strip() or f"kubectl exit {rc}")
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        return Endpoints(items=[], error="kubectl 출력 파싱 실패 (JSON 아님)")

    by_role: dict[str, Endpoint] = {}
    for item in data.get("items", []):
        name = item.get("metadata", {}).get("name", "")
        role = _role_for(name)
        if role is None:
            continue
        ing = item.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        hostname = ing[0].get("hostname") if ing else None
        by_role[role] = Endpoint(role=role, ingress_name=name, hostname=hostname)

    items = [by_role[r] for r in ORDER if r in by_role]
    return Endpoints(items=items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_postdeploy.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/tui/postdeploy.py deployment/tui/tests/test_postdeploy.py
git commit -m "feat(deploy-tui): discover_endpoints via label selector

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: live_healthcheck (Pod 상태 + ALB curl → 3-state)

**Files:**
- Modify: `deployment/tui/postdeploy.py`
- Test: `deployment/tui/tests/test_postdeploy.py`

**Interfaces:**
- Consumes: `Endpoints`, `Endpoint`, `HealthResult`, `HEALTH_PATH`, `_run_kubectl` (Task 1·2)
- Produces:
  - `live_healthcheck(endpoints: Endpoints, cluster_name="llm-gateway", namespace="llm-gateway") -> list[HealthResult]`
  - 내부 헬퍼 `_pod_health(cluster_name, namespace) -> HealthResult` 및 `_curl_status(url: str) -> int | None`(테스트가 `_curl_status` 를 monkeypatch; None = 연결 실패/타임아웃)

- [ ] **Step 1: Write the failing test**

`test_postdeploy.py` 에 추가:
```python
def _pods_json(states):
    # states: list of (phase, ready_bool)
    return json.dumps({
        "items": [
            {
                "status": {
                    "phase": phase,
                    "containerStatuses": [{"ready": ready}],
                }
            }
            for phase, ready in states
        ]
    })


def test_pod_health_counts_ready(monkeypatch):
    monkeypatch.setattr(pd, "_run_kubectl",
                        lambda args, cluster_name: (0, _pods_json([("Running", True)] * 6)))
    res = pd._pod_health("llm-gateway", "llm-gateway")
    assert res.state == "ok"
    assert "6" in res.detail


def test_pod_health_pending_when_not_all_ready(monkeypatch):
    monkeypatch.setattr(pd, "_run_kubectl",
                        lambda args, cluster_name: (0, _pods_json([("Running", True), ("Pending", False)])))
    res = pd._pod_health("llm-gateway", "llm-gateway")
    assert res.state == "pending"


def test_pod_health_check_on_kubectl_error(monkeypatch):
    monkeypatch.setattr(pd, "_run_kubectl", lambda args, cluster_name: (1, "boom"))
    res = pd._pod_health("llm-gateway", "llm-gateway")
    assert res.state == "check"


def test_live_healthcheck_maps_curl_status(monkeypatch):
    eps = pd.Endpoints(items=[
        pd.Endpoint("gateway", "llm-gateway-gateway", "g"),
        pd.Endpoint("admin-api", "llm-gateway-admin-api", "a"),
        pd.Endpoint("admin-ui", "llm-gateway-admin-ui", "u"),
    ])
    monkeypatch.setattr(pd, "_pod_health",
                        lambda c, n: pd.HealthResult("pods", "ok", "6/6"))
    status = {"http://g/health": 200, "http://a/health": 200, "http://u/": 307}
    monkeypatch.setattr(pd, "_curl_status", lambda url: status.get(url))
    results = pd.live_healthcheck(eps)
    # 1 pod row + 3 endpoint rows
    states = {r.label: r.state for r in results}
    assert all(s == "ok" for r, s in states.items() if r != "pods" or True)
    assert len([r for r in results]) == 4


def test_live_healthcheck_pending_on_connection_failure(monkeypatch):
    eps = pd.Endpoints(items=[pd.Endpoint("gateway", "llm-gateway-gateway", "g")])
    monkeypatch.setattr(pd, "_pod_health", lambda c, n: pd.HealthResult("pods", "ok", ""))
    monkeypatch.setattr(pd, "_curl_status", lambda url: None)  # refused/timeout
    results = pd.live_healthcheck(eps)
    gw = next(r for r in results if r.label != "pods")
    assert gw.state == "pending"


def test_live_healthcheck_pending_when_hostname_missing(monkeypatch):
    eps = pd.Endpoints(items=[pd.Endpoint("gateway", "llm-gateway-gateway", None)])
    monkeypatch.setattr(pd, "_pod_health", lambda c, n: pd.HealthResult("pods", "ok", ""))
    # hostname None → curl 호출 안 함. 호출되면 실패시키기 위해 예외 던지는 스텁.
    def boom(url):
        raise AssertionError("curl should not be called for missing hostname")
    monkeypatch.setattr(pd, "_curl_status", boom)
    results = pd.live_healthcheck(eps)
    gw = next(r for r in results if r.label != "pods")
    assert gw.state == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_postdeploy.py -k "health" -v`
Expected: FAIL — `AttributeError: ... '_pod_health'` / `live_healthcheck`

- [ ] **Step 3: Write minimal implementation**

`postdeploy.py` 에 함수 추가:
```python
def _pod_health(cluster_name: str, namespace: str) -> HealthResult:
    rc, out = _run_kubectl(["get", "pods", "-n", namespace, "-o", "json"], cluster_name)
    if rc != 0:
        return HealthResult(label="pods", state="check", detail=out.strip()[:60] or "kubectl 실패")
    try:
        items = json.loads(out).get("items", [])
    except (ValueError, TypeError):
        return HealthResult(label="pods", state="check", detail="pod 목록 파싱 실패")
    total = len(items)
    ready = 0
    for p in items:
        st = p.get("status", {})
        cs = st.get("containerStatuses", []) or []
        if st.get("phase") == "Running" and cs and all(c.get("ready") for c in cs):
            ready += 1
    state = "ok" if total > 0 and ready == total else "pending"
    return HealthResult(label="pods", state=state, detail=f"{ready}/{total} Ready")


def _curl_status(url: str) -> int | None:
    """HTTP 상태코드 반환. 연결실패/타임아웃/미설치는 None."""
    try:
        proc = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "10", url],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    code = proc.stdout.strip()
    return int(code) if code.isdigit() and code != "000" else None


def live_healthcheck(endpoints: Endpoints, cluster_name: str = "llm-gateway",
                     namespace: str = "llm-gateway") -> list[HealthResult]:
    results = [_pod_health(cluster_name, namespace)]
    for ep in endpoints.items:
        if ep.hostname is None:
            results.append(HealthResult(label=ep.role, state="pending", detail="ALB 프로비저닝 중"))
            continue
        path = HEALTH_PATH.get(ep.role, "/")
        code = _curl_status(f"{ep.url}{path}")
        if code is None:
            results.append(HealthResult(label=ep.role, state="pending", detail="연결 안 됨 (준비 중)"))
        elif 200 <= code < 400:
            results.append(HealthResult(label=ep.role, state="ok", detail=f"HTTP {code}"))
        else:
            results.append(HealthResult(label=ep.role, state="check", detail=f"HTTP {code}"))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_postdeploy.py -v`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/tui/postdeploy.py deployment/tui/tests/test_postdeploy.py
git commit -m "feat(deploy-tui): live_healthcheck pods + ALB curl 3-state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: cli 렌더 헬퍼 3개

**Files:**
- Modify: `deployment/tui/cli.py`
- Test: `deployment/tui/tests/test_cli.py`

**Interfaces:**
- Consumes: `postdeploy.Endpoints`, `postdeploy.Endpoint`, `postdeploy.HealthResult` (Task 1-3)
- Produces (cli.py 모듈 함수):
  - `render_endpoints_panel(endpoints: postdeploy.Endpoints) -> None`
  - `render_next_steps(env: str) -> None`
  - `render_health_table(results: list[postdeploy.HealthResult]) -> None`
  - 모듈 상수 `NEXT_STEPS_DOCS` (문서 경로 문자열들)

- [ ] **Step 1: Write the failing test**

`test_cli.py` 에 추가:
```python
from deployment.tui import postdeploy as pd


def test_render_endpoints_panel_shows_urls(capsys):
    eps = pd.Endpoints(items=[
        pd.Endpoint("admin-ui", "llm-gateway-admin-ui", "u.elb.amazonaws.com"),
    ])
    cli.render_endpoints_panel(eps)
    out = capsys.readouterr().out
    assert "u.elb.amazonaws.com" in out


def test_render_endpoints_panel_pending_message_when_empty(capsys):
    cli.render_endpoints_panel(pd.Endpoints(items=[]))
    out = capsys.readouterr().out
    assert "프로비저닝" in out or "준비" in out


def test_render_next_steps_includes_doc_path(capsys):
    cli.render_next_steps("dev")
    out = capsys.readouterr().out
    assert "08-post-deploy-tui.md" in out
    assert "KUBECONFIG" in out


def test_render_health_table_renders_all_states(capsys):
    results = [
        pd.HealthResult("pods", "ok", "6/6 Ready"),
        pd.HealthResult("gateway", "pending", "연결 안 됨"),
        pd.HealthResult("admin-ui", "check", "HTTP 500"),
    ]
    cli.render_health_table(results)
    out = capsys.readouterr().out
    assert "pods" in out and "gateway" in out and "admin-ui" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_cli.py -k "render" -v`
Expected: FAIL — `AttributeError: module 'deployment.tui.cli' has no attribute 'render_endpoints_panel'`

- [ ] **Step 3: Write minimal implementation**

`cli.py` import 블록에 추가:
```python
from . import config, paths, postdeploy, preflight
```
(기존 `from . import config, paths, preflight` 줄을 위 줄로 교체)

`cli.py` 에 상수/함수 추가(예: `_preview_steps` 근처):
```python
# 다음 단계 가이드에서 가리키는 리포 내 문서 경로(실제 위치라 상수).
NEXT_STEPS_DOCS = {
    "post_deploy": "deployment/docs/eks-fargate/08-post-deploy-tui.md",
    "cognito": "deployment/docs/eks-fargate/07-cognito-onboarding.md",
}

_STATE_MARK = {
    "ok": "[green]✓[/green]",
    "pending": "[yellow]⏳[/yellow]",
    "check": "[yellow]⚠[/yellow]",
}


def render_endpoints_panel(endpoints) -> None:
    """엔드포인트 3개 URL 을 표로. 비어있으면 프로비저닝 안내."""
    if endpoints.error:
        console.print(f"[yellow]엔드포인트 조회 실패[/yellow] — {endpoints.error}")
        console.print("[dim]KUBECONFIG 를 격리 파일로 맞췄는지 확인하세요.[/dim]")
        return
    if not endpoints.items or all(e.hostname is None for e in endpoints.items):
        console.print(
            "[yellow]ALB 프로비저닝 중[/yellow] — hostname 이 아직 없습니다.\n"
            "[dim]1~2분 뒤 메뉴 → '배포 검증'에서 다시 확인하세요.[/dim]"
        )
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("서비스")
    table.add_column("URL", style="cyan")
    for ep in endpoints.items:
        table.add_row(ep.role, ep.url or "[dim]프로비저닝 중[/dim]")
    console.print(Panel(table, title="접속 엔드포인트", border_style="cyan"))


def render_next_steps(env: str) -> None:
    """핵심 액션 + 문서 링크. 복붙 명령어 나열은 하지 않는다."""
    body = Text()
    body.append("다음 단계:\n", style="bold")
    body.append("  1. kubectl 컨텍스트: export KUBECONFIG=/tmp/llm-gateway.kubeconfig\n")
    body.append("  2. 준비되면(1~2분) 메뉴 → '배포 검증'으로 Pod/엔드포인트 헬스체크\n")
    body.append("  3. Admin UI 접속 → Cognito admin 온보딩 (첫 사용자 + 팀 그룹)\n")
    body.append("  4. 팀 budget 활성화 (기본 $0 + HARD_BLOCK → 활성화 전 모든 요청 429, 버그 아님)\n")
    console.print(Panel(body, title=f"배포 후 가이드 ({env})", border_style="green"))
    console.print(f"[dim]상세 가이드: {NEXT_STEPS_DOCS['post_deploy']}[/dim]")
    console.print(f"[dim]Cognito 온보딩: {NEXT_STEPS_DOCS['cognito']}[/dim]")


def render_health_table(results) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("항목")
    table.add_column("상태")
    table.add_column("detail", style="dim")
    for r in results:
        table.add_row(r.label, _STATE_MARK.get(r.state, r.state), r.detail)
    console.print(table)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_cli.py -k "render" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/tui/cli.py deployment/tui/tests/test_cli.py
git commit -m "feat(deploy-tui): render helpers for endpoints/next-steps/health

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 진입점 A — flow_llm 성공 직후 훅

**Files:**
- Modify: `deployment/tui/cli.py` (flow_llm 끝, `return run_and_report(...)` 부분)
- Test: `deployment/tui/tests/test_cli.py`

**Interfaces:**
- Consumes: `postdeploy.discover_endpoints`, `render_endpoints_panel`, `render_next_steps` (Task 2·4)
- Produces: 새 헬퍼 `_show_postdeploy_summary(env: str) -> None` (flow_llm 및 flow_verify 재사용). discover→panel→next_steps 를 호출하되 예외를 삼킨다.

- [ ] **Step 1: Write the failing test**

`test_cli.py` 에 추가:
```python
def test_show_postdeploy_summary_calls_discover_and_renders(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.postdeploy, "discover_endpoints",
                        lambda **k: calls.append("discover") or pd.Endpoints(items=[]))
    monkeypatch.setattr(cli, "render_endpoints_panel", lambda e: calls.append("panel"))
    monkeypatch.setattr(cli, "render_next_steps", lambda env: calls.append(f"steps:{env}"))
    cli._show_postdeploy_summary("dev")
    assert calls == ["discover", "panel", "steps:dev"]


def test_show_postdeploy_summary_swallows_errors(monkeypatch):
    # discover 가 터져도 배포 성공 흐름을 깨면 안 된다
    def boom(**k):
        raise RuntimeError("kubectl exploded")
    monkeypatch.setattr(cli.postdeploy, "discover_endpoints", boom)
    monkeypatch.setattr(cli, "render_next_steps", lambda env: None)
    cli._show_postdeploy_summary("dev")  # 예외 없이 반환


def test_flow_llm_shows_summary_on_success(monkeypatch):
    # flow_llm 이 배포 성공(run_and_report True) 후 summary 를 부르는지
    seen = []
    monkeypatch.setattr(cli, "_show_postdeploy_summary", lambda env: seen.append(env))
    cli._maybe_postdeploy(True, "dev")
    assert seen == ["dev"]
    seen.clear()
    cli._maybe_postdeploy(False, "dev")  # 실패면 호출 안 함
    assert seen == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_cli.py -k "summary or maybe_postdeploy" -v`
Expected: FAIL — `AttributeError: ... '_show_postdeploy_summary'`

- [ ] **Step 3: Write minimal implementation**

`cli.py` 에 헬퍼 추가:
```python
def _show_postdeploy_summary(env: str, cluster_name: str = "llm-gateway") -> None:
    """배포 직후: 엔드포인트 조회(curl 없음) + 다음 단계 가이드. 검증은 부수기능이라
    어떤 실패도 배포 성공 메시지를 덮지 않도록 예외를 삼킨다."""
    try:
        eps = postdeploy.discover_endpoints(cluster_name=cluster_name)
        render_endpoints_panel(eps)
    except Exception as exc:  # noqa: BLE001 - 배포 성공 흐름 보호가 우선
        console.print(f"[dim]엔드포인트 조회 건너뜀: {exc}[/dim]")
    render_next_steps(env)


def _maybe_postdeploy(deploy_ok: bool, env: str) -> None:
    if deploy_ok:
        _show_postdeploy_summary(env)
```

`flow_llm` 의 마지막 줄을 교체:
```python
    ok = run_and_report(wf, f"LLM Gateway {env}")
    _maybe_postdeploy(ok, env)
    return ok
```
(기존 `return run_and_report(wf, f"LLM Gateway {env}")` 대체)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_cli.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/tui/cli.py deployment/tui/tests/test_cli.py
git commit -m "feat(deploy-tui): auto endpoint+guide summary after successful deploy

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 진입점 B — flow_verify + MENU 항목

**Files:**
- Modify: `deployment/tui/cli.py` (flow_verify 신규, MENU 추가)
- Test: `deployment/tui/tests/test_cli.py`

**Interfaces:**
- Consumes: `postdeploy.discover_endpoints`, `postdeploy.live_healthcheck`, `render_endpoints_panel`, `render_health_table`, `render_next_steps`, `run_and_report`, `preflight`, `paths`, `postdeploy.isolated_kubeconfig`, `Step` (앞 Task 전부)
- Produces: `flow_verify() -> bool`; `MENU` 에 `("배포 검증 (Health Check)", flow_verify)` 추가(Teardown 앞).

- [ ] **Step 1: Write the failing test**

`test_cli.py` 에 추가:
```python
def test_menu_includes_verify():
    labels = [label for label, _ in cli.MENU]
    handlers = [h for _, h in cli.MENU]
    assert "배포 검증 (Health Check)" in labels
    assert cli.flow_verify in handlers


def test_flow_verify_runs_discover_health_and_smoke(monkeypatch):
    order = []
    monkeypatch.setattr(cli, "run_preflight", lambda tools: True)
    monkeypatch.setattr(cli, "ask_select", lambda msg, choices: "dev")
    monkeypatch.setattr(cli.postdeploy, "discover_endpoints",
                        lambda **k: order.append("discover") or pd.Endpoints(items=[]))
    monkeypatch.setattr(cli, "render_endpoints_panel", lambda e: order.append("panel"))
    monkeypatch.setattr(cli.postdeploy, "live_healthcheck",
                        lambda eps, **k: order.append("health") or [])
    monkeypatch.setattr(cli, "render_health_table", lambda r: order.append("htable"))
    monkeypatch.setattr(cli, "run_and_report",
                        lambda wf, title: order.append("smoke") or True)
    monkeypatch.setattr(cli, "render_next_steps", lambda env: order.append("steps"))
    assert cli.flow_verify() is True
    assert order == ["discover", "panel", "health", "htable", "smoke", "steps"]


def test_flow_verify_aborts_on_preflight_fail(monkeypatch):
    monkeypatch.setattr(cli, "run_preflight", lambda tools: False)
    ran = []
    monkeypatch.setattr(cli, "run_and_report", lambda wf, title: ran.append(title) or True)
    assert cli.flow_verify() is False
    assert ran == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/test_cli.py -k "verify" -v`
Expected: FAIL — `AttributeError: ... 'flow_verify'`

- [ ] **Step 3: Write minimal implementation**

`cli.py` 에 함수 추가(`flow_teardown` 앞):
```python
def flow_verify() -> bool:
    """배포 검증: 엔드포인트 조회 + 라이브 헬스체크 + smoke-test.sh. 읽기 전용이라
    파괴적 작업 아님. 배포가 이미 끝난 뒤 1~2분 지나 실행하는 용도."""
    console.rule("[bold]배포 검증 (Health Check)[/bold]")
    if not run_preflight(preflight.LLM_TOOLS):
        console.print("[red]사전검증 실패[/red] — 누락 도구/인증을 해결하세요.")
        return False
    env = ask_select("환경", ["dev", "prod"])

    eps = postdeploy.discover_endpoints()
    render_endpoints_panel(eps)

    console.rule("[bold]라이브 헬스체크[/bold]")
    render_health_table(postdeploy.live_healthcheck(eps))

    # smoke-test.sh 는 격리 KUBECONFIG 로. skippable — ALB 미준비 시 실패해도 검증 흐름 유지.
    kubeconfig = postdeploy.isolated_kubeconfig()
    smoke = [Step("smoke-test",
                  ["bash", str(paths.script("smoke-test.sh")), "--env", env],
                  env={"KUBECONFIG": kubeconfig},
                  skippable=True)]
    ok = run_and_report(smoke, f"smoke-test {env}")

    render_next_steps(env)
    return ok
```

`Step` import 추가 — `cli.py` 상단 `from .steps import (...)` 블록에 `Step` 을 넣는다:
```python
from .steps import (
    Step,
    build_llm_teardown,
    build_llm_workflow,
    build_tool_teardown,
    build_tool_workflow,
)
```

`MENU` 를 수정(Teardown 앞에 삽입):
```python
MENU = [
    ("LLM Gateway 배포", flow_llm),
    ("Tool Gateway 배포", flow_tool),
    ("전체 배포 (LLM → Tool)", flow_all),
    ("배포 검증 (Health Check)", flow_verify),
    ("스택 삭제 (Teardown)", flow_teardown),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && python -m pytest deployment/tui/tests/ -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/tui/cli.py deployment/tui/tests/test_cli.py
git commit -m "feat(deploy-tui): add 'Health Check' menu (endpoints+health+smoke)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 문서 반영

**Files:**
- Modify: `deployment/docs/eks-fargate/08-post-deploy-tui.md`

**Interfaces:** 없음 (문서만).

- [ ] **Step 1: 문서에 자동화 반영 한 줄 추가**

`08-post-deploy-tui.md` 의 "0. TUI 가 방금 뭘 했나" 표 아래 문단에 추가:
```markdown
> **v2부터**: TUI 는 LLM Gateway 배포가 성공하면 **접속 엔드포인트 3개 + 다음 단계 가이드**를 자동으로 출력한다(ALB 미준비 시 "프로비저닝 중" 안내). 1~2분 뒤 메인 메뉴의 **배포 검증 (Health Check)** 항목을 실행하면 Pod 상태·ALB 라이브 헬스체크·`smoke-test.sh` 를 한 번에 돌린다. 아래 수동 절차는 그 자동 출력을 사람이 재확인하거나 CI 없이 점검할 때 쓴다.
```

- [ ] **Step 2: 검증(문서 렌더 확인)**

Run: `cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway && grep -n "배포 검증 (Health Check)" deployment/docs/eks-fargate/08-post-deploy-tui.md`
Expected: 방금 추가한 줄이 출력됨

- [ ] **Step 3: Commit**

```bash
cd /home/ubuntu/workspace/sample-agentic-ai-acceleration-kr/projects/awsome-ai-gateway
git add deployment/docs/eks-fargate/08-post-deploy-tui.md
git commit -m "docs(deploy-tui): note auto endpoint summary + Health Check menu

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- 배포 직후 자동 엔드포인트+가이드 → Task 5 (진입점 A). ✓
- 메뉴 "배포 검증" = 라이브 헬스체크 + smoke-test → Task 6 (진입점 B). ✓
- discover_endpoints(라벨 셀렉터, hostname None 처리) → Task 2. ✓
- live_healthcheck(Pod + curl 3-state) → Task 3. ✓
- 렌더(패널/가이드/표) → Task 4. ✓
- 예외 안 던짐/3-state/빨간✗ 안 씀 → Task 1·3·5 에 반영. ✓
- 새 하드코딩 없음(파라미터화, 라벨 셀렉터, 상수는 helm/문서 규칙) → Task 1·2. ✓
- 다음 단계 가이드 텍스트(4줄+문서 2링크) → Task 4. ✓
- 문서 반영 → Task 7. ✓

**Placeholder scan:** 모든 step 에 실제 코드/명령/기대출력 포함. TBD/TODO 없음. ✓

**Type consistency:** `Endpoint`/`Endpoints`/`HealthResult` 필드, `discover_endpoints`/`live_healthcheck`/`isolated_kubeconfig`/`_run_kubectl`/`_pod_health`/`_curl_status` 시그니처가 Task 간 일치. cli 의 `render_*`/`_show_postdeploy_summary`/`_maybe_postdeploy`/`flow_verify` 이름 일치. `state` 값 `"ok"/"pending"/"check"` 일관. ✓

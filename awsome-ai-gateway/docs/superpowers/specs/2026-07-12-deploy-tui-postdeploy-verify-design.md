# Deploy TUI 배포 후 검증/안내 — 설계

**날짜**: 2026-07-12
**대상**: `deployment/tui/`
**목적**: `deploy-tui` 로 LLM Gateway 배포가 성공한 직후, 접속 엔드포인트와 다음 단계 가이드를 자동으로 띄우고, 별도 메뉴에서 라이브 헬스체크 + smoke-test 를 돌려 "인프라가 정말 뜨고 동작하는지" 검증할 수 있게 한다.

---

## 배경 / 문제

현재 TUI 는 `flow_llm()` 이 끝나면 `완료 — LLM Gateway dev` 한 줄만 출력한다. 사용자는:

- 웹페이지(Admin UI) 주소를 알 수 없다 → `kubectl get ingress` 를 손으로 쳐야 하고, 그 전에 격리 KUBECONFIG(`/tmp/llm-gateway.kubeconfig`) 를 export 해야 하는 함정이 있다.
- 다음에 뭘 해야 하는지(Cognito 온보딩, 팀 budget 활성화) 모른다 → `08-post-deploy-tui.md` 를 따로 열어야 한다.
- 인프라가 외부(ALB)에서 실제로 접근되는지 확인할 방법이 TUI 안에 없다.

이 내용은 이미 `08-post-deploy-tui.md` 문서로 정리돼 있으나, TUI 흐름 안에서 자동으로 노출되지 않는다.

## 목표 / 비목표

**목표**
- 배포 성공 직후 접속 엔드포인트 3개 + 다음 단계 핵심 액션 + 문서 링크를 자동 출력.
- 메인 메뉴에 "배포 검증 (Health Check)" 항목 추가 → 라이브 헬스체크 + `smoke-test.sh` 실행.
- 새로운 값 하드코딩 없음. 기존 상수/규칙(cluster_name, 격리 KUBECONFIG 경로, 라벨 셀렉터)만 재사용.

**비목표**
- 배포 직후 진입점에서 curl/헬스체크를 돌리지 않는다 (ALB 프로비저닝 1~2분 대기 회피).
- dev 전용 경로(`/internal/test/issue-key`, Bedrock 실호출)를 자동 검증에 넣지 않는다 — 문서 링크로만 안내.
- Cognito 온보딩 자동화는 범위 밖.

---

## 아키텍처

새 모듈 **`deployment/tui/postdeploy.py`** 를 추가한다. 기존 분리 원칙(배포 로직 = steps/runner, UI = cli)을 따라:

- `postdeploy.py` — **순수 조회/판정 로직**. kubectl·curl 을 subprocess 로 호출해 **구조화된 결과(dataclass)** 를 반환한다. 예외를 던지지 않는다(실패도 결과값으로 표현). rich 를 import 하지 않는다.
- `cli.py` — `postdeploy` 의 결과를 받아 rich 로 렌더링(패널/표). 두 진입점(배포 직후, 메뉴)을 연결.

`runner.py` 를 여기서 쓰지 않는 이유: runner 는 "argv 를 스트리밍 실행"하는 워크플로우용이고, 여기선 명령 출력을 파싱해 표로 만들어야 해서 성격이 다르다. 단, 메뉴 B 의 `smoke-test.sh` 실행은 argv 스트리밍이므로 기존 `run_and_report`(runner) 를 그대로 재사용한다.

### 데이터 구조

```python
@dataclass
class Endpoint:
    role: str            # "gateway" | "admin-api" | "admin-ui"
    ingress_name: str    # kubectl 이 준 실제 이름
    hostname: str | None # None = 아직 ALB 프로비저닝 중
    @property
    def url(self) -> str | None: ...   # "http://<hostname>" or None

@dataclass
class Endpoints:
    items: list[Endpoint]
    error: str | None = None           # kubectl 조회 자체 실패 시 힌트
    def by_role(self, role) -> Endpoint | None: ...

@dataclass
class HealthResult:
    label: str
    state: str           # "ok" | "pending" | "check"  (✓ / ⏳ / ⚠)
    detail: str          # "HTTP 200", "connection refused", "6/6 Running" 등
```

### 핵심 함수 (postdeploy.py)

- `isolated_kubeconfig(cluster_name="llm-gateway") -> str`
  `/tmp/{cluster_name}.kubeconfig` 경로 문자열. steps.py 와 동일 규칙 (상수 중복 아님 — 한 곳에서 파생).

- `discover_endpoints(cluster_name="llm-gateway", release="llm-gateway", namespace="llm-gateway") -> Endpoints`
  격리 KUBECONFIG 를 env 로 주입해 `kubectl get ingress -n <ns> -l app.kubernetes.io/instance=<release> -o json` 실행(타임아웃 15s). 각 ingress 의 `.metadata.name` suffix 로 role 매핑(`ROLE_SUFFIX` 상수), `.status.loadBalancer.ingress[0].hostname` 추출(없으면 None). kubectl 실패/미설치 → `Endpoints(items=[], error=<hint>)`.

- `live_healthcheck(endpoints, cluster_name="llm-gateway", namespace="llm-gateway") -> list[HealthResult]`
  1. Pod 상태: `kubectl get pods -n <ns> -o json` → Running/Ready 개수 집계 → 1개 행.
  2. 각 Endpoint 에 curl(타임아웃 10s): gateway/admin-api 는 `/health`, admin-ui 는 `/`. HTTP 코드로 3-state 매핑(2xx/3xx → ok, timeout/refused → pending, 그 외 → check).
  hostname 이 None 인 endpoint 는 curl 생략하고 pending 처리.

### 렌더 헬퍼 (cli.py)

- `render_endpoints_panel(endpoints)` — 3개 URL 을 rich Panel/Table 로. 비어있으면 "ALB 프로비저닝 중" 안내.
- `render_next_steps(env)` — 핵심 액션 목록 + 문서 링크(아래 "가이드 텍스트").
- `render_health_table(results)` — 3-state 를 색 마크(✓/⏳/⚠)로 표 출력.

### 상수 (postdeploy.py 모듈 상수 — 하드코딩이 아니라 구조 규칙)

```python
ROLE_SUFFIX = {"gateway": "gateway", "admin-api": "admin-api", "admin-ui": "admin-ui"}
HEALTH_PATH = {"gateway": "/health", "admin-api": "/health", "admin-ui": "/"}
```
role↔ingress suffix 매핑은 helm 차트 구조에서 오는 것이라 상수가 맞다. release_name/cluster_name/namespace 는 전부 파라미터(기본값 `llm-gateway`).

---

## 데이터 흐름 — 두 진입점

### 진입점 A — 배포 직후 (자동, 대기 없음)

`flow_llm()` 에서 `run_and_report(...) == True` 직후:
1. `discover_endpoints()` **1회** 호출 (curl 안 함).
2. hostname 있으면 → 엔드포인트 패널. 비어있으면 → "ALB 프로비저닝 중 — 1~2분 뒤 메뉴 '배포 검증'에서 확인" 안내.
3. `render_next_steps(env)` 출력.

curl/헬스체크는 하지 않는다(ALB 미준비 가능성).

### 진입점 B — 메인 메뉴 "배포 검증 (Health Check)"

`flow_verify()` 신규 핸들러. MENU 에 `("배포 검증 (Health Check)", flow_verify)` 추가(Teardown 위).
1. env(dev/prod) 선택 — smoke-test 인자 + kubeconfig 경로 파생에 필요.
2. `discover_endpoints()` → `render_endpoints_panel`.
3. `live_healthcheck()` → `render_health_table` (라이브 헬스체크).
4. `smoke-test.sh --env <env>` 를 격리 KUBECONFIG 로 실행(기존 `run_and_report` + Step 재사용, skippable).
5. `render_next_steps(env)`.

cluster_name/namespace/release 는 기본 `llm-gateway` 고정.

---

## 에러 처리

`postdeploy.py` 는 **어떤 실패에도 예외를 던지지 않는다**. 검증은 부수기능이라 배포 성공 메시지를 덮으면 안 된다.

- kubectl 없음/실패 → hostname `None`, `Endpoints.error` 에 힌트. 타임아웃 15s.
- ALB hostname 비어있음 → "프로비저닝 중" (정상 흐름).
- curl 타임아웃/연결거부 → `pending` (⏳), 실패 아님.
- smoke-test.sh 실패 → skippable, 경고만 (기존 run_and_report skippable 재사용).

**3-state 만 사용**: `✓ 정상` / `⏳ 준비 중` / `⚠ 확인 필요`. 빨간 ✗ 는 쓰지 않는다 — 검증 도구가 배포를 "실패"로 낙인찍지 않도록.

---

## 가이드 텍스트 (render_next_steps 출력 내용)

핵심 액션 + 문서 링크 (복붙 명령어 나열 안 함):

```
다음 단계:
  1. kubectl 컨텍스트: export KUBECONFIG=/tmp/llm-gateway.kubeconfig
  2. 준비되면(1~2분) 메뉴 → '배포 검증'으로 Pod/엔드포인트 헬스체크
  3. Admin UI 접속 → Cognito admin 온보딩 (첫 사용자 + 팀 그룹)
  4. 팀 budget 활성화 (기본 $0 + HARD_BLOCK → 활성화 전 모든 요청 429, 버그 아님)

상세 가이드: deployment/docs/eks-fargate/08-post-deploy-tui.md
Cognito 온보딩: deployment/docs/eks-fargate/07-cognito-onboarding.md
```

문서 경로는 리포 내 실제 위치라 상수로 둔다.

---

## 테스트

기존 `deployment/tui/` 테스트 패턴(subprocess 를 fake 로 격리)을 따른다. 네트워크/subprocess 는 전부 monkeypatch — 실제 호출 없이 CI 통과.

- `discover_endpoints`: kubectl 호출 monkeypatch → (a) 정상 JSON 3개, (b) hostname 빈 값, (c) kubectl 에러/미설치 → 파싱·None·error 처리 검증.
- `live_healthcheck`: curl 호출 monkeypatch → 200 / timeout / refused → 3-state 매핑 검증. hostname None → curl 생략 검증.
- 렌더 함수: rich 출력이라 "예외 안 남 + 핵심 문자열(URL, 문서 경로) 포함" 스모크 테스트.

---

## 변경 파일 요약

| 파일 | 변경 |
|------|------|
| `deployment/tui/postdeploy.py` | **신규** — 조회/판정 순수 로직 + dataclass + 상수 |
| `deployment/tui/cli.py` | `flow_llm` 끝에 진입점 A 훅 추가, `flow_verify` 신규, MENU 항목 추가, 렌더 헬퍼 3개 |
| `deployment/tui/steps.py` | (선택) smoke-test 단독 실행용 Step 빌더 재사용 — 기존 것으로 충분하면 변경 없음 |
| `deployment/tui/test_*.py` | postdeploy 단위 테스트 추가 |
| `deployment/docs/eks-fargate/08-post-deploy-tui.md` | (선택) "TUI 가 이제 자동으로 띄운다" 한 줄 반영 |

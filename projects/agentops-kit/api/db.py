"""
Aurora PostgreSQL 연결 모듈 (RDS Data API 기반).

RDS Data API는 HTTPS(443) + SigV4 서명으로 쿼리를 전송하므로:
- DB를 Public 접근 차단한 채로 사용 가능 (보안 강화)
- 기업 방화벽 우회 (TCP 5432 열 필요 없음)
- 연결 풀 관리 불필요 (stateless)
- Secrets Manager + IAM 기반 인증

환경변수:
    DB_CLUSTER_ARN  Aurora 클러스터 ARN
    DB_SECRET_ARN   Secrets Manager ARN
    DB_NAME         데이터베이스 이름 (기본: ecommerce)
    AWS_REGION      리전 (기본: us-east-1)
"""

import os
import functools
from pathlib import Path
from typing import Optional, Any

import boto3

# 프로젝트 루트의 .env 파일을 자동 로드 (쉘에서 source 없이도 동작)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass


@functools.lru_cache(maxsize=1)
def _get_client():
    return boto3.client("rds-data", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _get_config() -> tuple[str, str, str]:
    cluster_arn = os.getenv("DB_CLUSTER_ARN")
    secret_arn = os.getenv("DB_SECRET_ARN")
    dbname = os.getenv("DB_NAME", "ecommerce")
    if not cluster_arn or not secret_arn:
        raise RuntimeError("Database is not configured (missing DB_CLUSTER_ARN / DB_SECRET_ARN).")
    return cluster_arn, secret_arn, dbname


def _convert_value(field: dict) -> Any:
    """Data API의 field 응답 dict를 Python 값으로 변환."""
    if "isNull" in field and field["isNull"]:
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue"):
        if key in field:
            return field[key]
    if "arrayValue" in field:
        av = field["arrayValue"]
        for k, v in av.items():
            return v
    return None


def _to_params(params: Optional[dict]) -> list[dict]:
    """Python dict를 Data API parameter 형식으로 변환."""
    if not params:
        return []
    result = []
    for k, v in params.items():
        if v is None:
            result.append({"name": k, "value": {"isNull": True}})
        elif isinstance(v, bool):
            result.append({"name": k, "value": {"booleanValue": v}})
        elif isinstance(v, int):
            result.append({"name": k, "value": {"longValue": v}})
        elif isinstance(v, float):
            result.append({"name": k, "value": {"doubleValue": v}})
        else:
            result.append({"name": k, "value": {"stringValue": str(v)}})
    return result


def execute_query(sql: str, params: Optional[dict] = None) -> list[dict]:
    """SELECT 쿼리 실행 → list of dicts."""
    cluster_arn, secret_arn, dbname = _get_config()
    resp = _get_client().execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=dbname,
        sql=sql,
        parameters=_to_params(params),
        includeResultMetadata=True,
    )
    # 컬럼 이름 추출
    columns = [c["name"] for c in resp.get("columnMetadata", [])]
    rows = []
    for record in resp.get("records", []):
        rows.append({columns[i]: _convert_value(field) for i, field in enumerate(record)})
    return rows


def execute(sql: str, params: Optional[dict] = None) -> int:
    """DDL/DML 실행 → affected row count."""
    cluster_arn, secret_arn, dbname = _get_config()
    resp = _get_client().execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=dbname,
        sql=sql,
        parameters=_to_params(params),
    )
    return resp.get("numberOfRecordsUpdated", 0)


def batch_execute(sql: str, param_sets: list[dict]) -> int:
    """같은 SQL을 여러 parameter 세트로 실행 (마이그레이션용)."""
    if not param_sets:
        return 0
    cluster_arn, secret_arn, dbname = _get_config()
    resp = _get_client().batch_execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=dbname,
        sql=sql,
        parameterSets=[_to_params(p) for p in param_sets],
    )
    return len(resp.get("updateResults", []))


def ping() -> bool:
    """DB 연결 가능 여부 체크."""
    try:
        execute_query("SELECT 1 AS ok")
        return True
    except Exception:
        return False

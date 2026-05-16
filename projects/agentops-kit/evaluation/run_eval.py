"""
에이전트 평가 실행 스크립트.
test_cases.json의 골든 Q&A로 오프라인 평가를 수행합니다.

Usage:
    python evaluation/run_eval.py                    # V1 프롬프트로 평가
    python evaluation/run_eval.py --version v2       # V2 프롬프트로 평가
    python evaluation/run_eval.py --compare          # V1/V2 비교
"""

import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"


def load_test_cases() -> list[dict]:
    """테스트 케이스 로드."""
    with open(EVAL_DIR / "test_cases.json") as f:
        return json.load(f)


def run_agent_evaluation(test_cases: list[dict], prompt_version: str = "v1") -> list[dict]:
    """AgentCore Runtime으로 테스트 케이스 실행."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    from api.agentcore_runtime import invoke_runtime

    results = []

    print(f"\nRunning evaluation with prompt {prompt_version.upper()} (via AgentCore Runtime)")
    print(f"{'='*60}")

    for i, tc in enumerate(test_cases):
        print(f"  [{i+1}/{len(test_cases)}] {tc['id']}: {tc['prompt'][:50]}...", end=" ", flush=True)

        start = time.time()
        try:
            rt_result = invoke_runtime(tc["prompt"], prompt_version=prompt_version)
            response = rt_result.get("response", "")
            latency = round((time.time() - start) * 1000, 1)

            # 간단한 로컬 품질 체크
            has_numbers = any(c.isdigit() for c in response)
            keyword_hits = sum(
                1 for kw in tc.get("expected_keywords", [])
                if kw.lower() in response.lower()
            )
            keyword_total = len(tc.get("expected_keywords", []))
            keyword_score = keyword_hits / max(keyword_total, 1)

            results.append({
                "test_id": tc["id"],
                "category": tc["category"],
                "prompt": tc["prompt"],
                "response": response[:500],
                "latency_ms": latency,
                "has_numbers": has_numbers,
                "keyword_score": round(keyword_score, 2),
                "keyword_hits": keyword_hits,
                "keyword_total": keyword_total,
                "prompt_version": prompt_version,
                "status": "success",
            })
            print(f"OK ({latency}ms, keywords: {keyword_hits}/{keyword_total})")

        except Exception as e:
            latency = round((time.time() - start) * 1000, 1)
            results.append({
                "test_id": tc["id"],
                "category": tc["category"],
                "prompt": tc["prompt"],
                "error": str(e),
                "latency_ms": latency,
                "prompt_version": prompt_version,
                "status": "error",
            })
            print(f"ERROR ({e})")

    return results


def print_summary(results: list[dict], version: str):
    """평가 결과 요약 출력."""
    successful = [r for r in results if r["status"] == "success"]
    if not successful:
        print(f"\n  No successful results for {version.upper()}")
        return

    avg_latency = sum(r["latency_ms"] for r in successful) / len(successful)
    avg_keyword = sum(r["keyword_score"] for r in successful) / len(successful)
    numeric_rate = sum(1 for r in successful if r["has_numbers"]) / len(successful)

    print(f"\n{'='*60}")
    print(f"  Summary: Prompt {version.upper()}")
    print(f"{'='*60}")
    print(f"  Test cases: {len(results)} total, {len(successful)} success, {len(results) - len(successful)} error")
    print(f"  Avg latency: {avg_latency:.0f}ms")
    print(f"  Keyword score: {avg_keyword:.2%}")
    print(f"  Numeric data rate: {numeric_rate:.2%}")

    # 카테고리별
    categories = set(r["category"] for r in successful)
    for cat in sorted(categories):
        cat_results = [r for r in successful if r["category"] == cat]
        cat_keyword = sum(r["keyword_score"] for r in cat_results) / len(cat_results)
        print(f"    {cat}: keyword {cat_keyword:.2%} ({len(cat_results)} tests)")


def save_results(results: list[dict], version: str):
    """결과 저장."""
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"eval_{version}_{timestamp}.json"
    filepath = RESULTS_DIR / filename

    with open(filepath, "w") as f:
        json.dump({
            "prompt_version": version,
            "timestamp": datetime.now().isoformat(),
            "test_count": len(results),
            "results": results,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n  Results saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Run agent evaluation")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"], help="Prompt version")
    parser.add_argument("--compare", action="store_true", help="Run both V1 and V2, then compare")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of test cases (0=all)")
    args = parser.parse_args()

    test_cases = load_test_cases()
    if args.limit > 0:
        test_cases = test_cases[:args.limit]

    print(f"Loaded {len(test_cases)} test cases")

    if args.compare:
        v1_results = run_agent_evaluation(test_cases, "v1")
        print_summary(v1_results, "v1")
        save_results(v1_results, "v1")

        v2_results = run_agent_evaluation(test_cases, "v2")
        print_summary(v2_results, "v2")
        save_results(v2_results, "v2")

        # 비교
        v1_success = [r for r in v1_results if r["status"] == "success"]
        v2_success = [r for r in v2_results if r["status"] == "success"]

        if v1_success and v2_success:
            v1_keyword = sum(r["keyword_score"] for r in v1_success) / len(v1_success)
            v2_keyword = sum(r["keyword_score"] for r in v2_success) / len(v2_success)
            delta = v2_keyword - v1_keyword

            print(f"\n{'='*60}")
            print(f"  COMPARISON: V1 vs V2")
            print(f"{'='*60}")
            print(f"  V1 keyword score: {v1_keyword:.2%}")
            print(f"  V2 keyword score: {v2_keyword:.2%}")
            print(f"  Improvement: {'+' if delta > 0 else ''}{delta:.2%}")
    else:
        results = run_agent_evaluation(test_cases, args.version)
        print_summary(results, args.version)
        save_results(results, args.version)


if __name__ == "__main__":
    main()

"""Regression harness and release gate for `/why` answer quality.

Runs `GOLDEN_SET` through `canon.answer_why` and scores each case:

  citation_hit  — did it cite the decision it should have?
  keyword_hit   — does it talk about the right thing? (cheap substring proxy)
  judge         — LLM-as-judge against prompts/judge.md, LIVE only, and
                  observe-only until it's earned the right to gate.

In MOCK mode this is deterministic and needs no API keys, so
`tests/test_eval_harness.py` runs it as a CI gate. In LIVE mode it exercises
the real path — agent loop or v1 pipeline, whichever is enabled — which is
what makes the two comparable: same questions, same store, same scoring.

    python -m app.eval.harness              # score the active path
    python -m app.eval.harness --compare    # agent vs pipeline, side by side

One caveat the numbers can't show: the agent path is non-deterministic. A
single run is a sample, not a measurement. Treat a one-case swing as noise
and look at the rate.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings
from app.eval.golden_set import GOLDEN_SET, GoldenCase
from app.eval.judge import UNAVAILABLE, Verdict, judge
from app.retrieval import canon


@dataclass
class CaseResult:
    question: str
    decision_id: str
    passed: bool
    citation_hit: bool
    keyword_hit: bool
    latency_s: float
    answer: str
    hops: int = 0
    guardrail: Optional[str] = None
    verdict: Verdict = field(default_factory=lambda: UNAVAILABLE)
    reasons: list[str] = field(default_factory=list)


def _citation_hit(must_cite: str, sources: list) -> bool:
    for entry in sources:
        # Sources are [kind, label] or [kind, label, url].
        label = entry[1] if isinstance(entry, (list, tuple)) and len(entry) > 1 else entry
        if must_cite.lower() in str(label).lower():
            return True
    return False


def _keyword_hit(must_include_any: list[str], answer: str) -> bool:
    a = (answer or "").lower()
    return any(k.lower() in a for k in must_include_any)


def run_case(case: GoldenCase, scope: str, with_judge: bool = False) -> CaseResult:
    result = canon.answer_why(case["question"], scope)
    sources = result.get("sources") or []
    answer = result.get("answer", "")

    citation_hit = _citation_hit(case["must_cite"], sources)
    keyword_hit = _keyword_hit(case["must_include_any"], answer)

    reasons = []
    if not citation_hit:
        reasons.append(f"expected a citation containing {case['must_cite']!r}, "
                       f"got sources={sources}")
    if not keyword_hit:
        reasons.append(f"expected one of {case['must_include_any']} in the answer")

    verdict = UNAVAILABLE
    if with_judge:
        retrieved = [{"source": s[1] if isinstance(s, (list, tuple)) and len(s) > 1 else s,
                      "text": ""} for s in sources]
        verdict = judge(case["question"], answer, retrieved)
        if verdict.available and verdict.grounded < 2:
            reasons.append(f"judge: {verdict.note or 'ungrounded claim'}")

    return CaseResult(
        question=case["question"], decision_id=case["decision_id"],
        passed=citation_hit and keyword_hit, citation_hit=citation_hit,
        keyword_hit=keyword_hit, latency_s=result.get("latency_s", 0.0),
        answer=answer, hops=result.get("hops", 0),
        guardrail=result.get("guardrail"), verdict=verdict, reasons=reasons,
    )


def run_eval(scope: str = "demo", with_judge: Optional[bool] = None) -> dict:
    with_judge = settings.judge_enabled if with_judge is None else with_judge
    results = [run_case(case, scope, with_judge=with_judge) for case in GOLDEN_SET]
    n = len(results) or 1
    passed = sum(r.passed for r in results)
    judged = [r.verdict for r in results if r.verdict.available]

    return {
        "mode": settings.mode,
        "path": canon.status()["path"],
        "total": len(results),
        "passed": passed,
        "hit_rate": round(passed / n, 3),
        "citation_accuracy": round(sum(r.citation_hit for r in results) / n, 3),
        "keyword_accuracy": round(sum(r.keyword_hit for r in results) / n, 3),
        "avg_latency_s": round(sum(r.latency_s for r in results) / n, 3),
        "avg_hops": round(sum(r.hops for r in results) / n, 2),
        "judge_score": round(sum(v.normalised for v in judged) / len(judged), 3) if judged else None,
        "judged_cases": len(judged),
        "results": results,
    }


def gate(report: dict) -> tuple[bool, list[str]]:
    """The release gate. Returns (passed, failures).

    The judge is intentionally not part of this yet — see app/eval/judge.py.
    Add it here once its scores have been checked against human reading."""
    failures = []
    if report["hit_rate"] < settings.eval_hit_rate_floor:
        failures.append(
            f"hit_rate {report['hit_rate']} < floor {settings.eval_hit_rate_floor}")
    if report["citation_accuracy"] < settings.eval_citation_floor:
        failures.append(
            f"citation_accuracy {report['citation_accuracy']} < "
            f"floor {settings.eval_citation_floor}")
    return (not failures), failures


def _print_report(report: dict) -> bool:
    print(f"mode={report['mode']} path={report['path']}  "
          f"passed={report['passed']}/{report['total']}  "
          f"hit_rate={report['hit_rate']}  citation={report['citation_accuracy']}  "
          f"keyword={report['keyword_accuracy']}  avg_hops={report['avg_hops']}  "
          f"avg_latency_s={report['avg_latency_s']}")
    if report["judge_score"] is not None:
        print(f"  judge_score={report['judge_score']} over {report['judged_cases']} cases "
              f"(observe-only)")
    for r in report["results"]:
        print(f"  [{'PASS' if r.passed else 'FAIL'}] {r.question}"
              + (f"  ({r.hops} hops)" if r.hops else "")
              + (f"  guardrail={r.guardrail}" if r.guardrail else ""))
        for reason in r.reasons:
            print(f"         - {reason}")

    passed, failures = gate(report)
    print(f"\ngate: {'PASS' if passed else 'FAIL'}")
    for f in failures:
        print(f"  - {f}")
    return passed


def _compare(scope: str) -> None:
    """Score both paths back to back. The point of keeping the v1 pipeline
    around is that the loop has to out-perform something."""
    original = settings.agent_loop_enabled
    try:
        for enabled, label in ((False, "pipeline (v1)"), (True, "agent (v2)")):
            settings.agent_loop_enabled = enabled
            print(f"\n=== {label} ===")
            _print_report(run_eval(scope))
    finally:
        settings.agent_loop_enabled = original


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the /why regression eval.")
    parser.add_argument("--scope", default="demo", help="Canon scope to query.")
    parser.add_argument("--judge", action="store_true",
                        help="Run the LLM judge (LIVE mode only).")
    parser.add_argument("--compare", action="store_true",
                        help="Score the v1 pipeline and the v2 agent side by side.")
    args = parser.parse_args()

    if args.compare:
        _compare(args.scope)
        return

    # Exit non-zero when the gate fails, so CI actually blocks on it rather
    # than printing "FAIL" into a green build.
    passed = _print_report(run_eval(args.scope, with_judge=args.judge or None))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()

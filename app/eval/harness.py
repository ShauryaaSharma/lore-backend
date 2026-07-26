"""Regression harness for `/why` answer quality.

Runs `GOLDEN_SET` through `canon.answer_why` and checks two things per case:
did the answer cite the decision it should have (`citation_hit`), and does
it actually talk about the right thing (`keyword_hit`, a cheap relevance
proxy — no LLM judge, no extra dependency, just substring checks against
words a correct answer would plausibly use).

In MOCK mode (default, no API keys) this is deterministic and fast enough
to run as a CI gate — `tests/test_eval_harness.py` asserts a hit-rate floor
on it. In LIVE mode it exercises the real mem0 search + rerank + Groq path;
run it manually (`python -m app.eval.harness`) after touching retrieval or
reranking to see the effect on the real thing, not just the mock stand-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.eval.golden_set import GOLDEN_SET, GoldenCase
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
    reasons: list[str] = field(default_factory=list)


def _citation_hit(must_cite: str, sources: list) -> bool:
    return any(must_cite.lower() in str(label).lower() for _, label in sources)


def _keyword_hit(must_include_any: list[str], answer: str) -> bool:
    a = answer.lower()
    return any(k.lower() in a for k in must_include_any)


def run_case(case: GoldenCase, scope: str) -> CaseResult:
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

    return CaseResult(
        question=case["question"], decision_id=case["decision_id"],
        passed=citation_hit and keyword_hit, citation_hit=citation_hit,
        keyword_hit=keyword_hit, latency_s=result.get("latency_s", 0.0),
        answer=answer, reasons=reasons,
    )


def run_eval(scope: str = "demo") -> dict:
    results = [run_case(case, scope) for case in GOLDEN_SET]
    n = len(results) or 1
    passed = sum(r.passed for r in results)
    return {
        "mode": settings.mode,
        "total": len(results),
        "passed": passed,
        "hit_rate": round(passed / n, 3),
        "citation_accuracy": round(sum(r.citation_hit for r in results) / n, 3),
        "keyword_accuracy": round(sum(r.keyword_hit for r in results) / n, 3),
        "avg_latency_s": round(sum(r.latency_s for r in results) / n, 3),
        "results": results,
    }


def _print_report(report: dict) -> None:
    print(f"mode={report['mode']}  passed={report['passed']}/{report['total']}  "
          f"hit_rate={report['hit_rate']}  citation_accuracy={report['citation_accuracy']}  "
          f"keyword_accuracy={report['keyword_accuracy']}  "
          f"avg_latency_s={report['avg_latency_s']}")
    for r in report["results"]:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.question}")
        for reason in r.reasons:
            print(f"         - {reason}")


def main() -> None:
    _print_report(run_eval())


if __name__ == "__main__":
    main()

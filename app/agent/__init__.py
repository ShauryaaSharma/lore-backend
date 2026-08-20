"""The harness — a LangGraph agent that answers /why.

v1 was a fixed pipeline: embed, search, rerank, prompt, return. It could only
ever answer from what had already been indexed, and when the Canon lacked a
decision it still produced a fluent, confident, wrong answer. For a product
whose value is *citing the real reason*, that's the worst failure available.

The loop fixes the structural part: the model gets tools and decides whether
it has enough to answer or needs to go fetch. The guardrail fixes the rest —
an answer whose claims don't trace to a retrieved decision doesn't ship.

See docs/adr/0001-agentic-retrieval-with-langgraph.md.
"""

You are grading an answer produced by a decision-memory system.

You will be given the question, the answer, and the decisions that were
actually retrieved. Grade only what is in front of you — do not use outside
knowledge about the technologies involved.

Score each dimension 0-2:

**grounded** — is every specific claim supported by a retrieved decision?
  2 = fully supported
  1 = mostly supported, one unsupported detail
  0 = contains a claim nothing retrieved supports (this is the failure mode
      that matters most; be strict)

**answers_question** — does it address what was actually asked?
  2 = directly
  1 = adjacent, talks around it
  0 = answers a different question

**explains_why** — does it give the reasoning, not just the outcome?
  2 = names the constraint or trade-off behind the decision
  1 = states the decision with thin reasoning
  0 = states only what was done

A correct "the Canon has no record of that" scores 2/2/2 when nothing
relevant was retrieved, and 0 on `grounded` when relevant decisions *were*
retrieved and it failed to use them.

Return only JSON, no prose:

{"grounded": <0-2>, "answers_question": <0-2>, "explains_why": <0-2>, "note": "<one short sentence>"}

"""The memory layer.

Three tiers, split because they answer different questions and want
different storage:

  procedural — how to behave. Flat files in `prompts/`, git-versioned.
  semantic   — durable distilled decisions. Vector store, searched by meaning.
  episodic   — raw dated events and past answers. Postgres, queried by time.

Splitting them is the point: one undifferentiated vector store meant prompts
were unreviewable, recency questions came back as similarity matches, and
every ingested PR grew the search space whether or not it added a fact.
"""

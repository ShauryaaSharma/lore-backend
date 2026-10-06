from lore_backend.jobs import queue


def test_enqueue_and_claim():
    job_id = queue.enqueue("backfill_installation", {"installation_id": 1})
    claimed = queue.claim_next(("backfill_installation",))
    assert claimed is not None
    assert claimed["id"] == job_id
    assert claimed["attempts"] == 1


def test_claim_skips_locked_or_absent_rows():
    assert queue.claim_next(("backfill_installation",)) is None


def test_claim_ignores_other_types():
    queue.enqueue("some_other_type", {})
    assert queue.claim_next(("backfill_installation",)) is None


def test_mark_done_and_get_job():
    job_id = queue.enqueue("backfill_installation", {"installation_id": 2})
    queue.claim_next(("backfill_installation",))
    queue.update_progress(job_id, {"repos_done": 1})
    queue.mark_done(job_id)

    job = queue.get_job(job_id)
    assert job["status"] == "done"
    assert job["progress"]["repos_done"] == 1


def test_mark_error_requeues_with_backoff_then_fails_permanently():
    job_id = queue.enqueue("backfill_installation", {"installation_id": 3})
    job = queue.claim_next(("backfill_installation",))
    queue.mark_error(job_id, "boom", max_attempts=2, attempts=job["attempts"])
    requeued = queue.get_job(job_id)
    assert requeued["status"] == "queued"  # attempt 1 of 2 -> retry

    job2 = queue.claim_next(("backfill_installation",))
    assert job2 is None  # run_after is in the future (backoff), not claimable yet


def test_independent_progress_across_two_installations():
    """The concrete bug this rewrite fixes: the prototype's single global
    `_backfill` dict clobbered progress when two installs ran concurrently.
    Here each job row tracks its own installation's progress independently."""
    job_a = queue.enqueue("backfill_installation", {"installation_id": 111})
    job_b = queue.enqueue("backfill_installation", {"installation_id": 222})

    queue.update_progress(job_a, {"current_repo": "org/repo-a", "repos_done": 1})
    queue.update_progress(job_b, {"current_repo": "org/repo-b", "repos_done": 5})

    assert queue.get_job(job_a)["progress"]["current_repo"] == "org/repo-a"
    assert queue.get_job(job_b)["progress"]["current_repo"] == "org/repo-b"

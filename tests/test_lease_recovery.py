from dreamgraph.lease_recovery import WriterLeaseRecovery


def test_restarts_after_persistent_lease_errors_at_most_three_times():
    now = [0.0]
    restarts = []
    recovery = WriterLeaseRecovery(
        restart_after=60,
        max_restarts=3,
        clock=lambda: now[0],
        restart=lambda: restarts.append(now[0]),
    )
    lease_error = RuntimeError("cell cell-0 is not owned by this node; owner: unknown")

    assert recovery.handle_error(lease_error)
    now[0] = 59.9
    assert recovery.handle_error(lease_error)
    assert restarts == []

    for expected_count in range(1, 4):
        now[0] += 0.1
        assert recovery.handle_error(lease_error)
        assert len(restarts) == expected_count
        now[0] += 60

    assert recovery.handle_error(lease_error)
    assert recovery.restart_count == 3
    assert len(restarts) == 3
    assert recovery.handle_error(RuntimeError("parse error")) is False


def test_success_resets_the_persistence_timer():
    now = [0.0]
    restarts = []
    recovery = WriterLeaseRecovery(
        restart_after=60,
        clock=lambda: now[0],
        restart=lambda: restarts.append(now[0]),
    )
    lease_error = RuntimeError("not owned by this node")

    assert recovery.handle_error(lease_error)
    now[0] = 59
    recovery.reset()
    now[0] = 60
    assert recovery.handle_error(lease_error)
    assert restarts == []
    now[0] = 120
    assert recovery.handle_error(lease_error)
    assert restarts == [120]

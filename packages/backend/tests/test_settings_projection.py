from backend_core.settings_projection import ResolvedSettingsSnapshot, _get_resolved_snapshot


def test_each_projection_reads_current_database_settings(monkeypatch) -> None:
    from backend_core import database

    snapshots = iter(
        (
            ResolvedSettingsSnapshot(exists=True, smtp_host='host-before'),
            ResolvedSettingsSnapshot(exists=True, smtp_host='host-after'),
        )
    )
    reads: list[None] = []

    def read_settings(_loader):
        reads.append(None)
        return next(snapshots)

    monkeypatch.setattr(database, 'run_settings_db', read_settings)

    before = _get_resolved_snapshot()
    after = _get_resolved_snapshot()

    assert before.smtp_host == 'host-before'
    assert after.smtp_host == 'host-after'
    assert len(reads) == 2

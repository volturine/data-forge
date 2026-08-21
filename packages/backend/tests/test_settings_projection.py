import gc

from backend_core.settings_projection import (
    ResolvedSettingsSnapshot,
    _get_resolved_snapshot,
    invalidate_resolved_settings_cache,
)


class _FakeEngine:
    pass


def _patch_database(monkeypatch):
    from backend_core import database

    state = {'engine': None}
    loads: list[int] = []

    def fake_get_settings_engine():
        return state['engine']

    def fake_run_settings_db(func, *args, **kwargs):
        loads.append(1)
        return ResolvedSettingsSnapshot(exists=True, smtp_host=f'host-{len(loads)}')

    monkeypatch.setattr(database, 'get_settings_engine', fake_get_settings_engine)
    monkeypatch.setattr(database, 'run_settings_db', fake_run_settings_db)
    invalidate_resolved_settings_cache()
    return state, loads


def test_same_engine_is_cached_without_reload(monkeypatch) -> None:
    state, loads = _patch_database(monkeypatch)

    state['engine'] = _FakeEngine()
    first = _get_resolved_snapshot()
    second = _get_resolved_snapshot()

    assert len(loads) == 1
    assert first.smtp_host == second.smtp_host == 'host-1'


def test_distinct_engines_do_not_share_cached_entries(monkeypatch) -> None:
    state, loads = _patch_database(monkeypatch)

    engine_a = _FakeEngine()
    engine_b = _FakeEngine()

    state['engine'] = engine_a
    snapshot_a = _get_resolved_snapshot()
    state['engine'] = engine_b
    snapshot_b = _get_resolved_snapshot()
    state['engine'] = engine_a
    cached_a = _get_resolved_snapshot()

    assert len(loads) == 2
    assert snapshot_a.smtp_host == cached_a.smtp_host
    assert snapshot_b.smtp_host != snapshot_a.smtp_host


def test_garbage_collected_engine_does_not_serve_stale_entry(monkeypatch) -> None:
    import weakref

    state, loads = _patch_database(monkeypatch)
    refs: list[weakref.ref] = []

    state['engine'] = _FakeEngine()
    refs.append(weakref.ref(state['engine']))
    first = _get_resolved_snapshot()
    assert len(loads) == 1

    # Simulate the engine being replaced: old engine becomes unreachable.
    state['engine'] = _FakeEngine()
    gc.collect()
    assert refs[0]() is None

    fresh = _get_resolved_snapshot()

    # With id()-keyed caching, a recycled id() could serve `first` here;
    # weakref keying guarantees a reload for the new engine object.
    assert len(loads) == 2
    assert fresh is not first
    assert fresh.smtp_host == 'host-2' != first.smtp_host


def test_invalidate_clears_all_engine_entries(monkeypatch) -> None:
    from backend_core.settings_projection import _RESOLVED_CACHE

    state, loads = _patch_database(monkeypatch)

    engines = [_FakeEngine(), _FakeEngine()]
    state['engine'] = engines[0]
    _get_resolved_snapshot()
    state['engine'] = engines[1]
    _get_resolved_snapshot()
    assert len(_RESOLVED_CACHE) == 2

    invalidate_resolved_settings_cache()
    assert len(_RESOLVED_CACHE) == 0

    state['engine'] = engines[0]
    _get_resolved_snapshot()
    assert len(loads) == 3

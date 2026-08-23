from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend_core.datasource_storage import DatasourceStorageCleanup


def _make_datasource(dataset_id: str, metadata_path: str):
    return SimpleNamespace(
        id=dataset_id,
        is_iceberg=True,
        source_type_kind=lambda: None,
        config={
            'catalog_type': 'sql',
            'catalog_uri': '',
            'warehouse': 's3://bucket/warehouse',
            'namespace': 'outputs',
            'table': f'{dataset_id}_master_rev0001abcd',
            'metadata_path': metadata_path,
        },
    )


def _client():
    client = MagicMock()
    client.classify_object_url.return_value = SimpleNamespace(is_managed=True)
    client.__enter__.return_value = client
    return client


def test_revision_swap_delete_removes_original_branch_dir() -> None:
    dataset_id = 'e33c95d1-3606-40b2-bc61-e91e6bfc67b9'
    revision_path = f's3://bucket/exports/{dataset_id}/master/revision_ab12cd34'
    datasource = _make_datasource(dataset_id, revision_path)
    client = _client()

    with (
        patch('backend_core.datasource_storage.client_from_settings', return_value=client),
        patch('backend_core.datasource_storage.load_runtime_catalog') as catalog_factory,
    ):
        catalog = catalog_factory.return_value
        catalog.list_tables.return_value = [
            ('outputs', f'{dataset_id}_master'),
            ('outputs', f'{dataset_id}_master_rev0001abcd'),
        ]
        DatasourceStorageCleanup().delete(datasource)

    deleted = [call.args[0] for call in client.delete_managed_prefix.call_args_list]
    assert revision_path in deleted
    assert f's3://bucket/exports/{dataset_id}' in deleted
    dropped = [call.args[0] for call in catalog.drop_table.call_args_list]
    assert f'outputs.{dataset_id}_master' in dropped
    assert f'outputs.{dataset_id}_master_rev0001abcd' in dropped


def test_clean_datasource_deletes_family_root() -> None:
    dataset_id = 'aa11bb22'
    datasource = _make_datasource(dataset_id, f's3://bucket/clean/{dataset_id}/master')
    client = _client()

    with (
        patch('backend_core.datasource_storage.client_from_settings', return_value=client),
        patch('backend_core.datasource_storage.load_runtime_catalog') as catalog_factory,
    ):
        catalog = catalog_factory.return_value
        catalog.list_tables.return_value = [('clean', dataset_id)]
        DatasourceStorageCleanup().delete(datasource)

    deleted = [call.args[0] for call in client.delete_managed_prefix.call_args_list]
    assert f's3://bucket/clean/{dataset_id}' in deleted


def test_unmanaged_paths_are_not_deleted() -> None:
    dataset_id = 'cc33dd44'
    external_path = f's3://external-bucket/exports/{dataset_id}/master'
    datasource = _make_datasource(dataset_id, external_path)
    client = _client()
    client.classify_object_url.return_value = SimpleNamespace(is_managed=False)

    with (
        patch('backend_core.datasource_storage.client_from_settings', return_value=client),
        patch('backend_core.datasource_storage.load_runtime_catalog') as catalog_factory,
    ):
        catalog = catalog_factory.return_value
        catalog.list_tables.return_value = []
        DatasourceStorageCleanup().delete(datasource)

    client.delete_managed_prefix.assert_not_called()


def test_family_cleanup_failure_does_not_block_metadata_path_delete() -> None:
    dataset_id = 'ee55ff66'
    metadata_path = f's3://bucket/exports/{dataset_id}/master/revision_badbad99'
    datasource = _make_datasource(dataset_id, metadata_path)
    client = _client()
    # Primary metadata_path delete succeeds; the family prefix classify fails.
    client.classify_object_url.side_effect = [
        SimpleNamespace(is_managed=True),
        RuntimeError('data plane down'),
    ]

    with (
        patch('backend_core.datasource_storage.client_from_settings', return_value=client),
        patch('backend_core.datasource_storage.load_runtime_catalog') as catalog_factory,
    ):
        catalog = catalog_factory.return_value
        catalog.list_tables.return_value = []
        DatasourceStorageCleanup().delete(datasource)

    deleted = [call.args[0] for call in client.delete_managed_prefix.call_args_list]
    assert metadata_path in deleted
    assert f's3://bucket/exports/{dataset_id}' not in deleted

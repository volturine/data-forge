"""Unit tests for UDF module."""

import pytest

from modules.udf.schemas import (
    UdfCreateSchema,
    UdfImportItemSchema,
    UdfImportSchema,
    UdfInputSchema,
    UdfSignatureSchema,
    UdfUpdateSchema,
)
from modules.udf.service import create_udf, delete_udf, get_udf, import_udfs, list_udfs, update_udf


class TestUdfValidation:
    """Test UDF code validation."""

    def test_create_udf_with_valid_code(self, test_db_session):
        """Test creating a UDF with valid Python code."""
        udf_data = UdfCreateSchema(
            name='test_add',
            description='Add two numbers',
            signature=UdfSignatureSchema(
                inputs=[
                    UdfInputSchema(position=0, dtype='Float64', label='a'),
                    UdfInputSchema(position=1, dtype='Float64', label='b'),
                ],
                output_dtype='Float64',
            ),
            code='def udf(a, b):\n    return a + b',
            tags=['math', 'test'],
        )

        result = create_udf(test_db_session, udf_data)

        assert result.name == 'test_add'
        assert result.description == 'Add two numbers'
        assert result.code == 'def udf(a, b):\n    return a + b'
        assert result.tags == ['math', 'test']
        assert result.source == 'user'

    def test_create_udf_with_empty_code(self, test_db_session):
        """Test creating a UDF with empty code raises error."""
        udf_data = UdfCreateSchema(
            name='test_empty',
            description='Empty UDF',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='',
        )

        with pytest.raises(ValueError, match='UDF code cannot be empty'):
            create_udf(test_db_session, udf_data)

    def test_create_udf_with_whitespace_only_code(self, test_db_session):
        """Test creating a UDF with whitespace-only code raises error."""
        udf_data = UdfCreateSchema(
            name='test_whitespace',
            description='Whitespace UDF',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='   \n\t  ',
        )

        with pytest.raises(ValueError, match='UDF code cannot be empty'):
            create_udf(test_db_session, udf_data)

    def test_create_udf_with_invalid_syntax(self, test_db_session):
        """Test creating a UDF with invalid Python syntax raises error."""
        udf_data = UdfCreateSchema(
            name='test_syntax',
            description='Invalid syntax',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return invalid syntax here',
        )

        with pytest.raises(ValueError, match='Invalid Python syntax'):
            create_udf(test_db_session, udf_data)

    def test_update_udf_with_invalid_code(self, test_db_session):
        """Test updating a UDF with invalid code raises error."""
        # First create a valid UDF
        udf_data = UdfCreateSchema(
            name='test_update',
            description='Update test',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return "valid"',
        )
        created = create_udf(test_db_session, udf_data)

        # Try to update with invalid code
        update_data = UdfUpdateSchema(code='def udf():\n    invalid syntax')

        with pytest.raises(ValueError, match='Invalid Python syntax'):
            update_udf(test_db_session, created.id, update_data)


class TestUdfCRUD:
    """Test UDF CRUD operations."""

    def test_get_udf(self, test_db_session):
        """Test getting a UDF by ID."""
        udf_data = UdfCreateSchema(
            name='test_get',
            description='Get test',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return "test"',
        )
        created = create_udf(test_db_session, udf_data)

        result = get_udf(test_db_session, created.id)

        assert result.id == created.id
        assert result.name == 'test_get'

    def test_get_nonexistent_udf(self, test_db_session):
        """Test getting a non-existent UDF raises error."""
        with pytest.raises(ValueError, match='UDF .* not found'):
            get_udf(test_db_session, 'nonexistent-id')

    def test_update_udf(self, test_db_session):
        """Test updating a UDF."""
        udf_data = UdfCreateSchema(
            name='test_update',
            description='Original description',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return "original"',
            tags=['original'],
        )
        created = create_udf(test_db_session, udf_data)

        update_data = UdfUpdateSchema(
            name='test_updated',
            description='Updated description',
            code='def udf():\n    return "updated"',
            tags=['updated'],
        )
        updated = update_udf(test_db_session, created.id, update_data)

        assert updated.id == created.id
        assert updated.name == 'test_updated'
        assert updated.description == 'Updated description'
        assert updated.code == 'def udf():\n    return "updated"'
        assert updated.tags == ['updated']
        assert updated.updated_at > created.created_at

    def test_delete_udf(self, test_db_session):
        """Test deleting a UDF."""
        udf_data = UdfCreateSchema(
            name='test_delete',
            description='Delete test',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return "delete"',
        )
        created = create_udf(test_db_session, udf_data)

        delete_udf(test_db_session, created.id)

        # Verify it's deleted
        with pytest.raises(ValueError, match='UDF .* not found'):
            get_udf(test_db_session, created.id)

    def test_delete_nonexistent_udf(self, test_db_session):
        """Test deleting a non-existent UDF raises error."""
        with pytest.raises(ValueError, match='UDF .* not found'):
            delete_udf(test_db_session, 'nonexistent-id')


class TestUdfListing:
    """Test UDF listing and filtering."""

    def test_list_all_udfs(self, test_db_session):
        """Test listing all UDFs."""
        # Create multiple UDFs
        for i in range(3):
            udf_data = UdfCreateSchema(
                name=f'test_udf_{i}',
                description=f'Test UDF {i}',
                signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                code=f'def udf():\n    return "test_{i}"',
            )
            create_udf(test_db_session, udf_data)

        result = list_udfs(test_db_session)

        assert len(result) == 3
        names = {udf.name for udf in result}
        assert names == {'test_udf_0', 'test_udf_1', 'test_udf_2'}

    def test_list_udfs_with_text_search(self, test_db_session):
        """Test listing UDFs with text search filter."""
        udf1 = UdfCreateSchema(
            name='calculate_sum',
            description='Calculates the sum',
            signature=UdfSignatureSchema(inputs=[], output_dtype='Float64'),
            code='def udf():\n    return 0',
        )
        udf2 = UdfCreateSchema(
            name='calculate_product',
            description='Calculates the product',
            signature=UdfSignatureSchema(inputs=[], output_dtype='Float64'),
            code='def udf():\n    return 1',
        )
        udf3 = UdfCreateSchema(
            name='format_string',
            description='Formats a string',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return ""',
        )

        create_udf(test_db_session, udf1)
        create_udf(test_db_session, udf2)
        create_udf(test_db_session, udf3)

        # Search for "calculate"
        result = list_udfs(test_db_session, query='calculate')
        assert len(result) == 2
        names = {udf.name for udf in result}
        assert names == {'calculate_sum', 'calculate_product'}

        # Search for "sum"
        result = list_udfs(test_db_session, query='sum')
        assert len(result) == 1
        assert result[0].name == 'calculate_sum'

    def test_list_udfs_with_tag_filter(self, test_db_session):
        """Test listing UDFs with tag filter."""
        udf1 = UdfCreateSchema(
            name='math_func',
            description='Math function',
            signature=UdfSignatureSchema(inputs=[], output_dtype='Float64'),
            code='def udf():\n    return 0',
            tags=['math', 'numeric'],
        )
        udf2 = UdfCreateSchema(
            name='string_func',
            description='String function',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return ""',
            tags=['string', 'text'],
        )
        udf3 = UdfCreateSchema(
            name='another_math',
            description='Another math function',
            signature=UdfSignatureSchema(inputs=[], output_dtype='Float64'),
            code='def udf():\n    return 1',
            tags=['math'],
        )

        create_udf(test_db_session, udf1)
        create_udf(test_db_session, udf2)
        create_udf(test_db_session, udf3)

        # Filter by 'math' tag
        result = list_udfs(test_db_session, tag='math')
        assert len(result) == 2
        names = {udf.name for udf in result}
        assert names == {'math_func', 'another_math'}

        # Filter by 'string' tag
        result = list_udfs(test_db_session, tag='string')
        assert len(result) == 1
        assert result[0].name == 'string_func'


class TestUdfImport:
    """Test UDF import with transaction safety."""

    def test_import_new_udfs(self, test_db_session):
        """Test importing new UDFs."""
        import_data = UdfImportSchema(
            udfs=[
                UdfImportItemSchema(
                    name='import_test_1',
                    description='Import test 1',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    return "1"',
                ),
                UdfImportItemSchema(
                    name='import_test_2',
                    description='Import test 2',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    return "2"',
                ),
            ],
            overwrite=False,
        )

        result = import_udfs(test_db_session, import_data)

        assert len(result) == 2
        names = {udf.name for udf in result}
        assert names == {'import_test_1', 'import_test_2'}

    def test_import_with_invalid_code_rolls_back(self, test_db_session):
        """Test that import with invalid code rolls back entire transaction."""
        import_data = UdfImportSchema(
            udfs=[
                UdfImportItemSchema(
                    name='valid_1',
                    description='Valid UDF 1',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    return "valid1"',
                ),
                UdfImportItemSchema(
                    name='invalid',
                    description='Invalid UDF',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    invalid syntax here',
                ),
                UdfImportItemSchema(
                    name='valid_2',
                    description='Valid UDF 2',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    return "valid2"',
                ),
            ],
            overwrite=False,
        )

        # Import should fail due to invalid code
        with pytest.raises(ValueError, match='Invalid Python syntax'):
            import_udfs(test_db_session, import_data)

        # Verify no UDFs were created (transaction rolled back)
        all_udfs = list_udfs(test_db_session)
        assert len(all_udfs) == 0

    def test_import_with_overwrite(self, test_db_session):
        """Test importing UDFs with overwrite enabled."""
        # Create initial UDF
        initial = UdfCreateSchema(
            name='overwrite_test',
            description='Original description',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return "original"',
            tags=['original'],
        )
        created = create_udf(test_db_session, initial)

        # Import with overwrite
        import_data = UdfImportSchema(
            udfs=[
                UdfImportItemSchema(
                    name='overwrite_test',
                    description='Updated description',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    return "updated"',
                    tags=['updated'],
                ),
            ],
            overwrite=True,
        )

        result = import_udfs(test_db_session, import_data)

        assert len(result) == 1
        assert result[0].id == created.id  # Same ID
        assert result[0].description == 'Updated description'
        assert result[0].code == 'def udf():\n    return "updated"'
        assert result[0].tags == ['updated']

    def test_import_without_overwrite_skips_existing(self, test_db_session):
        """Test importing UDFs without overwrite skips existing."""
        # Create initial UDF
        initial = UdfCreateSchema(
            name='skip_test',
            description='Original',
            signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
            code='def udf():\n    return "original"',
        )
        create_udf(test_db_session, initial)

        # Import without overwrite
        import_data = UdfImportSchema(
            udfs=[
                UdfImportItemSchema(
                    name='skip_test',
                    description='Should be skipped',
                    signature=UdfSignatureSchema(inputs=[], output_dtype='String'),
                    code='def udf():\n    return "skipped"',
                ),
            ],
            overwrite=False,
        )

        result = import_udfs(test_db_session, import_data)

        # No UDFs returned because existing was skipped
        assert len(result) == 0

        # Verify original UDF unchanged
        existing = list_udfs(test_db_session)
        assert len(existing) == 1
        assert existing[0].description == 'Original'


class TestUdfAPI:
    """Test UDF API endpoints."""

    def test_create_udf_endpoint(self, client):
        """Test creating a UDF via API."""
        udf_data = {
            'name': 'api_test',
            'description': 'API test UDF',
            'signature': {'inputs': [], 'output_dtype': 'String'},
            'code': 'def udf():\n    return "api"',
            'tags': ['api', 'test'],
        }

        response = client.post('/api/v1/udf', json=udf_data)

        assert response.status_code == 200
        result = response.json()
        assert result['name'] == 'api_test'
        assert result['description'] == 'API test UDF'

    def test_create_udf_with_invalid_code_returns_400(self, client):
        """Test creating a UDF with invalid code returns 400."""
        udf_data = {
            'name': 'invalid_api_test',
            'description': 'Invalid UDF',
            'signature': {'inputs': [], 'output_dtype': 'String'},
            'code': 'invalid python syntax',
        }

        response = client.post('/api/v1/udf', json=udf_data)

        assert response.status_code == 400
        assert 'Invalid Python syntax' in response.json()['detail']

    def test_list_udfs_endpoint(self, client):
        """Test listing UDFs via API."""
        # Get initial count (may include seeded UDFs)
        initial_response = client.get('/api/v1/udf')
        initial_count = len(initial_response.json())

        # Create some UDFs
        for i in range(3):
            udf_data = {
                'name': f'list_test_{i}',
                'description': f'List test {i}',
                'signature': {'inputs': [], 'output_dtype': 'String'},
                'code': f'def udf():\n    return "{i}"',
            }
            client.post('/api/v1/udf', json=udf_data)

        response = client.get('/api/v1/udf')

        assert response.status_code == 200
        result = response.json()
        assert len(result) == initial_count + 3

    def test_list_udfs_with_query_filter(self, client):
        """Test listing UDFs with query filter via API."""
        client.post(
            '/api/v1/udf',
            json={
                'name': 'math_add',
                'description': 'Add numbers',
                'signature': {'inputs': [], 'output_dtype': 'Float64'},
                'code': 'def udf():\n    return 0',
            },
        )
        client.post(
            '/api/v1/udf',
            json={
                'name': 'string_concat',
                'description': 'Concatenate strings',
                'signature': {'inputs': [], 'output_dtype': 'String'},
                'code': 'def udf():\n    return ""',
            },
        )

        response = client.get('/api/v1/udf?q=math')

        assert response.status_code == 200
        result = response.json()
        assert len(result) == 1
        assert result[0]['name'] == 'math_add'

import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture
def sample_datasource(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("id,name,value\n1,Alice,10\n2,Bob,20\n3,Cara,30\n4,Dan,40\n5,Eve,50\n", encoding="utf-8")
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        name="Sample datasource",
        source_type="file",
        config={
            "source_type": "file",
            "file_path": str(csv_path),
            "file_type": "csv",
            "options": {},
        },
    )

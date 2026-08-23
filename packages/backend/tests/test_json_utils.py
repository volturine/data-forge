import pytest

from backend_core.json_utils import copy_json_dict, copy_json_object


def test_copy_json_dict_deep_copies_nested_structures():
    source = {'tabs': [{'id': 'tab-1', 'config': {'limit': 10}}], 'tags': {'a': [1, 2]}}

    copied = copy_json_dict(source)

    assert copied == source
    copied['tabs'][0]['config']['limit'] = 99
    copied['tags']['a'].append(3)
    assert source['tabs'][0]['config']['limit'] == 10
    assert source['tags']['a'] == [1, 2]


def test_copy_json_dict_raises_type_error_for_non_dict():
    with pytest.raises(TypeError):
        copy_json_dict([{'not': 'a dict'}])
    with pytest.raises(TypeError):
        copy_json_dict('string')
    with pytest.raises(TypeError):
        copy_json_dict(None)


def test_copy_json_object_returns_none_for_non_dict():
    assert copy_json_object(None) is None
    assert copy_json_object([]) is None


def test_copy_json_object_deep_copies():
    source = {'nested': {'value': 1}}
    copied = copy_json_object(source)
    assert copied is not None
    copied['nested']['value'] = 2
    assert source['nested']['value'] == 1

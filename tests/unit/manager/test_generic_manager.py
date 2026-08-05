# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.manager.generic_manager.GenericManager

Pure tests: no Mongo. Each CRUD method is invoked unbound with a MagicMock standing in for the
manager instance, so the DB-touching collaborators (insert / get_one / iterate_query / update /
delete) are stubbed and only the method's own branching + exception mapping is exercised. A small
real _StubModel stands in for the CmdbDAO model so the isinstance(...) serialisation branches and
the to_json / from_data calls behave like the real thing
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.generic_manager import GenericManager
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.manager.generic_manager'

PUBLIC_ID: int = 42
RAW_DOC: dict[str, Any] = {'public_id': PUBLIC_ID, 'name': 'sample'}
SERIALIZED_DOC: dict[str, Any] = {**RAW_DOC, 'serialized': True}


class _StubModel:
    """Minimal real model stand-in (a real class so isinstance(...) and the classmethods work)."""
    COLLECTION = 'stub.collection'

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    @classmethod
    def to_json(cls, instance: "_StubModel") -> dict[str, Any]:
        """Serialises the instance (matches SERIALIZED_DOC) so callers can assert it was used."""
        return {**instance.data, 'serialized': True}

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "_StubModel":
        """Wraps the raw document in a _StubModel so the result is identifiable."""
        return cls(data)


# Distinct exception types per operation so a test can assert the correct one is raised
class _InsertErr(Exception):
    """Stub 'insert' exception."""


class _GetErr(Exception):
    """Stub 'get' exception."""


class _IterateErr(Exception):
    """Stub 'iterate' exception."""


class _UpdateErr(Exception):
    """Stub 'update' exception."""


class _DeleteErr(Exception):
    """Stub 'delete' exception."""


EXCEPTIONS: dict[str, type[Exception]] = {
    'insert': _InsertErr,
    'get': _GetErr,
    'iterate': _IterateErr,
    'update': _UpdateErr,
    'delete': _DeleteErr,
}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a GenericManager, wired with the stub model + exception map."""
    mgr = MagicMock()
    mgr.model = _StubModel
    mgr.exceptions = EXCEPTIONS
    return mgr


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  insert_item                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_insert_item_inserts_dict_unchanged() -> None:
    """A dict document is passed straight to insert() and its public_id returned"""
    mgr = _mock_manager()
    mgr.insert.return_value = PUBLIC_ID

    result = GenericManager.insert_item(mgr, RAW_DOC)

    mgr.insert.assert_called_once_with(RAW_DOC)
    assert result == PUBLIC_ID


def test_insert_item_serialises_model_instance_before_insert() -> None:
    """A model instance is serialised via to_json() before being inserted"""
    mgr = _mock_manager()
    mgr.insert.return_value = PUBLIC_ID

    result = GenericManager.insert_item(mgr, _StubModel(RAW_DOC))

    mgr.insert.assert_called_once_with(SERIALIZED_DOC)
    assert result == PUBLIC_ID


def test_insert_item_wraps_failure_in_insert_exception() -> None:
    """A failure during insert is wrapped in the configured 'insert' exception"""
    mgr = _mock_manager()
    mgr.insert.side_effect = RuntimeError('boom')

    with pytest.raises(_InsertErr):
        GenericManager.insert_item(mgr, RAW_DOC)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    get_item                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_item_returns_none_when_not_found() -> None:
    """A missing document yields None without attempting deserialisation"""
    mgr = _mock_manager()
    mgr.get_one.return_value = None

    assert GenericManager.get_item(mgr, PUBLIC_ID) is None


def test_get_item_returns_raw_doc_when_as_dict() -> None:
    """as_dict=True returns the raw document unchanged"""
    mgr = _mock_manager()
    mgr.get_one.return_value = RAW_DOC

    assert GenericManager.get_item(mgr, PUBLIC_ID, as_dict=True) == RAW_DOC


def test_get_item_returns_model_instance_by_default() -> None:
    """as_dict=False (default) deserialises the document via from_data()"""
    mgr = _mock_manager()
    mgr.get_one.return_value = RAW_DOC

    result = GenericManager.get_item(mgr, PUBLIC_ID)

    assert isinstance(result, _StubModel)
    assert result.data == RAW_DOC


def test_get_item_wraps_failure_in_get_exception() -> None:
    """A failure during retrieval is wrapped in the configured 'get' exception"""
    mgr = _mock_manager()
    mgr.get_one.side_effect = RuntimeError('boom')

    with pytest.raises(_GetErr):
        GenericManager.get_item(mgr, PUBLIC_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  iterate_items                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_iterate_items_builds_iteration_result() -> None:
    """The (results, total) from iterate_query is wrapped in IterationResult(results, total, model)"""
    mgr = _mock_manager()
    results = [{'public_id': PUBLIC_ID}]
    mgr.iterate_query.return_value = (results, 1)
    params = MagicMock()

    with patch(f'{PATH}.IterationResult') as mock_iteration_result:
        out = GenericManager.iterate_items(mgr, params)

    mgr.iterate_query.assert_called_once_with(params)
    mock_iteration_result.assert_called_once_with(results, 1, _StubModel)
    assert out is mock_iteration_result.return_value


def test_iterate_items_wraps_failure_in_iterate_exception() -> None:
    """A failure during iteration is wrapped in the configured 'iterate' exception"""
    mgr = _mock_manager()
    mgr.iterate_query.side_effect = RuntimeError('boom')

    with pytest.raises(_IterateErr):
        GenericManager.iterate_items(mgr, MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   update_item                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_item_updates_with_dict_unchanged() -> None:
    """A dict update is applied as-is, filtered by public_id"""
    mgr = _mock_manager()

    GenericManager.update_item(mgr, PUBLIC_ID, RAW_DOC)

    mgr.update.assert_called_once_with({'public_id': PUBLIC_ID}, RAW_DOC)


def test_update_item_serialises_model_instance_before_update() -> None:
    """A model instance is serialised via to_json() before the update"""
    mgr = _mock_manager()

    GenericManager.update_item(mgr, PUBLIC_ID, _StubModel(RAW_DOC))

    mgr.update.assert_called_once_with({'public_id': PUBLIC_ID}, SERIALIZED_DOC)


def test_update_item_wraps_failure_in_update_exception() -> None:
    """A failure during update is wrapped in the configured 'update' exception"""
    mgr = _mock_manager()
    mgr.update.side_effect = RuntimeError('boom')

    with pytest.raises(_UpdateErr):
        GenericManager.update_item(mgr, PUBLIC_ID, RAW_DOC)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   delete_item                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_item_delegates_to_delete() -> None:
    """delete_item filters by public_id and returns delete()'s boolean result"""
    mgr = _mock_manager()
    mgr.delete.return_value = True

    result = GenericManager.delete_item(mgr, PUBLIC_ID)

    mgr.delete.assert_called_once_with({'public_id': PUBLIC_ID})
    assert result is True


def test_delete_item_wraps_failure_in_delete_exception() -> None:
    """A failure during deletion is wrapped in the configured 'delete' exception"""
    mgr = _mock_manager()
    mgr.delete.side_effect = RuntimeError('boom')

    with pytest.raises(_DeleteErr):
        GenericManager.delete_item(mgr, PUBLIC_ID)

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
from datetime import datetime, timezone
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
    DATE_FIELDS: tuple[str, ...] = ()

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

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """No-op hook, as CmdbDAO's default is: a real model may fill in its empty values here."""



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


class _InitErr(Exception):
    """Stub 'init' exception."""


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


def test_insert_item_runs_the_models_document_normalisation() -> None:
    """
    A dict inserted as-is still gets the model's own normalisation

    The write routes hand the validated payload straight to insert_item, so this is the only place
    that can stop a payload's null (or an omitted optional key) from becoming a stored null. The
    model instance path needs no equivalent - to_json produces normalised values by construction.
    """
    mgr = _mock_manager()

    def _fill(document: dict[str, Any]) -> None:
        document['normalized'] = True

    mgr._normalize_document.side_effect = _fill  # pylint: disable=protected-access

    GenericManager.insert_item(mgr, dict(RAW_DOC))

    assert mgr.insert.call_args.args[0]['normalized'] is True


def test_the_normalisation_hook_is_optional() -> None:
    """
    Not every model of a GenericManager is a CmdbDAO - CmdbUserSetting is not

    Calling the hook unconditionally turned every user-setting write into a 400, which is why it is
    read with getattr and skipped when the model declares none.
    """
    mgr = _mock_manager()
    mgr.model = type('_Hookless', (), {'COLLECTION': 'x', 'DATE_FIELDS': ()})

    GenericManager._normalize_document(mgr, dict(RAW_DOC))  # pylint: disable=protected-access


def test_the_normalisation_hook_is_used_when_the_model_declares_one() -> None:
    """A CmdbDAO model's hook is what fills in the empty values before a raw insert."""
    mgr = _mock_manager()
    document: dict[str, Any] = dict(RAW_DOC)

    def _fill(data: dict[str, Any]) -> None:
        data['normalized'] = True

    with patch.object(_StubModel, 'normalize_document', staticmethod(_fill)):
        GenericManager._normalize_document(mgr, document)  # pylint: disable=protected-access

    assert document['normalized'] is True


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _normalize_dates                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class _DatedModel(_StubModel):
    """A model that opts its collection into date normalisation."""
    COLLECTION = 'stub.dated'
    DATE_FIELDS: tuple[str, ...] = ('from', 'to')


STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)


def _dated_manager() -> MagicMock:
    """A MagicMock standing in for a GenericManager over the dated stub model."""
    mgr = MagicMock()
    mgr.model = _DatedModel
    mgr.exceptions = EXCEPTIONS
    mgr._normalize_dates = lambda document: GenericManager._normalize_dates(mgr, document)

    return mgr


class _ModelWithoutDateFields:
    """A model that does not extend CmdbDAO at all, the way CmdbUserSetting does not."""
    COLLECTION = 'stub.no_dao'

    @classmethod
    def to_json(cls, instance: Any) -> dict[str, Any]:
        """Never reached by these tests; present so the class is a usable model."""
        return dict(instance)


def test_normalize_dates_tolerates_a_model_that_is_not_a_cmdb_dao() -> None:
    """
    Not every model this manager is built with extends CmdbDAO, so DATE_FIELDS may be absent.

    CmdbUserSetting is one: reading the attribute directly turned every user-settings write into a
    manager insert error.
    """
    mgr = MagicMock()
    mgr.model = _ModelWithoutDateFields
    mgr.exceptions = EXCEPTIONS
    document: dict[str, Any] = {'from': {'$date': STAMP_MILLIS}}

    GenericManager._normalize_dates(mgr, document)

    assert document == {'from': {'$date': STAMP_MILLIS}}


def test_normalize_dates_is_a_no_op_without_declared_date_fields() -> None:
    """
    Every collection that declares no dates is left exactly as it was.

    This is what keeps the mechanism opt-in: the default DATE_FIELDS on CmdbDAO is empty, so nothing
    outside the two ISMS collections is touched.
    """
    mgr = _mock_manager()
    document: dict[str, Any] = {'from': {'$date': STAMP_MILLIS}}

    GenericManager._normalize_dates(mgr, document)

    assert document == {'from': {'$date': STAMP_MILLIS}}


def test_normalize_dates_converts_the_declared_fields() -> None:
    """A raw document reaches the database with real dates, not the wrapper the frontend sends"""
    mgr = _dated_manager()
    document: dict[str, Any] = {'from': {'$date': STAMP_MILLIS}, 'to': '2020-09-13T12:26:40Z'}

    GenericManager._normalize_dates(mgr, document)

    assert document == {'from': STAMP, 'to': STAMP}


def test_normalize_dates_raises_on_an_unreadable_date() -> None:
    """Refusing beats guessing: a wrong date is stored as confidently as a correct one"""
    mgr = _dated_manager()

    with pytest.raises(ValueError, match='from'):
        GenericManager._normalize_dates(mgr, {'from': 'planned for Q3'})


def test_insert_item_normalizes_a_raw_document_s_dates() -> None:
    """
    The write path that takes a dict is the one that used to store the wrapper.

    Both ISMS insert routes hand the validated payload straight to insert_item, so this is where the
    shape has to be settled.
    """
    mgr = _dated_manager()
    mgr.insert.return_value = PUBLIC_ID

    GenericManager.insert_item(mgr, {'public_id': PUBLIC_ID, 'from': {'$date': STAMP_MILLIS}})

    mgr.insert.assert_called_once_with({'public_id': PUBLIC_ID, 'from': STAMP})


def test_insert_item_does_not_normalize_a_model_instance() -> None:
    """A model instance has already normalised its own dates in from_data"""
    mgr = _dated_manager()
    mgr.insert.return_value = PUBLIC_ID

    GenericManager.insert_item(mgr, _DatedModel({'public_id': PUBLIC_ID}))

    mgr.insert.assert_called_once_with({'public_id': PUBLIC_ID, 'serialized': True})


def test_insert_item_wraps_an_unreadable_date_in_the_insert_exception() -> None:
    """The route maps that exception to a 400, so nothing is written"""
    mgr = _dated_manager()

    with pytest.raises(_InsertErr):
        GenericManager.insert_item(mgr, {'from': 'planned for Q3'})

    mgr.insert.assert_not_called()


def test_insert_many_items_normalizes_every_document() -> None:
    """A bulk create cannot bypass what the single-document path enforces"""
    mgr = _dated_manager()
    mgr.insert_many.return_value = [1, 2]
    documents = [{'from': {'$date': STAMP_MILLIS}}, {'from': '2020-09-13T12:26:40Z'}]

    result = GenericManager.insert_many_items(mgr, documents)

    mgr.insert_many.assert_called_once_with([{'from': STAMP}, {'from': STAMP}])
    assert result == [1, 2]


def test_insert_many_items_wraps_failure_in_insert_exception() -> None:
    """One unreadable date refuses the whole batch rather than storing part of it"""
    mgr = _dated_manager()

    with pytest.raises(_InsertErr):
        GenericManager.insert_many_items(mgr, [{'from': {'$date': STAMP_MILLIS}}, {'from': 'nonsense'}])

    mgr.insert_many.assert_not_called()


def test_update_item_normalizes_a_raw_update_s_dates() -> None:
    """A dict update reaches $set with real dates too"""
    mgr = _dated_manager()

    GenericManager.update_item(mgr, PUBLIC_ID, {'from': {'$date': STAMP_MILLIS}})

    mgr.update.assert_called_once_with({'public_id': PUBLIC_ID}, {'from': STAMP})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     __init__                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_init_wraps_a_failing_setup_in_the_init_exception() -> None:
    """
    A manager that cannot be built reports it as its own domain error.

    The routes resolve managers through ManagerProvider, so a bare exception here would surface with
    no indication of which manager failed. BaseManager reads the default database name off the
    manager, which is what fails when there is none.
    """
    exceptions: dict[str, type[Exception]] = {**EXCEPTIONS, 'init': _InitErr}

    with pytest.raises(_InitErr):
        GenericManager(None, _StubModel, exceptions)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            find_existing_public_ids                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_existing_public_ids_reads_the_ids_in_one_projected_query() -> None:
    """
    One '$in' query projected to public_id, rather than a read per referenced id

    The callers validate a list of references before a write (a person's groups, a group's members),
    so the cost has to stay independent of how many ids the payload names.
    """
    mgr = _mock_manager()
    mgr.find.return_value = [{'public_id': 1}, {'public_id': 3}]

    result = GenericManager.find_existing_public_ids(mgr, [1, 2, 3])

    mgr.find.assert_called_once_with(
        criteria={'public_id': {'$in': [1, 2, 3]}},
        projection={'public_id': 1},
    )
    assert result == {1, 3}


def test_find_existing_public_ids_reports_nothing_for_an_empty_selection() -> None:
    """
    No ids to check means no query - an empty '$in' would still be a round trip

    It also keeps the caller's 'unknown = wanted - existing' arithmetic correct for a payload that
    references nothing.
    """
    mgr = _mock_manager()

    assert GenericManager.find_existing_public_ids(mgr, []) == set()
    mgr.find.assert_not_called()


def test_find_existing_public_ids_accepts_a_set() -> None:
    """The routes compute their reference sets with set arithmetic and pass them straight in."""
    mgr = _mock_manager()
    mgr.find.return_value = [{'public_id': 5}]

    assert GenericManager.find_existing_public_ids(mgr, {5}) == {5}


def test_find_existing_public_ids_wraps_failure_in_get_exception() -> None:
    """A lookup failure is the manager's 'get' error, like every other read here."""
    mgr = _mock_manager()
    mgr.find.side_effect = RuntimeError('boom')

    with pytest.raises(_GetErr):
        GenericManager.find_existing_public_ids(mgr, [1])

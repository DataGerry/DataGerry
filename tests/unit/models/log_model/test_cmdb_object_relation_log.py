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
Unit tests for cmdb.models.log_model.cmdb_object_relation_log

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what belongs to the audit entry itself:

  - **nothing is invented.** The constructor used to default ``creation_time`` to ``datetime.now()``,
    so an entry that did not carry one reported *today*, differently on every read - on the one
    collection whose entire content is "when did this happen"
  - **nothing is refused either.** The model declares no ``REQUIRED_INIT_KEYS``, deliberately and
    unlike every other model swept recently: history has to stay readable when an entry predates a key
    the writer added later, and an unreadable history is a worse failure than an incomplete one
  - **an unreadable timestamp is the one exception**, because a plausible wrong date is worse than
    none: the previous implementation parsed with ``fuzzy=True``
  - ``changes`` has one empty state, the ``{}`` the log builder writes
  - the two indexes the only real query needs, and the one that is kept for the delete route
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_COLLECTIONS
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.log_model import (
    CmdbObjectRelationLog,
    LogInteraction,
    OBJECT_RELATION_LOG_DATE_KEYS,
    ObjectRelationLogKey,
)
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.cmdb_object_relation_log import (
    CmdbObjectRelationLogInitError,
    CmdbObjectRelationLogInitFromDataError,
    CmdbObjectRelationLogToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 31
OBJECT_RELATION_ID: int = 7
PARENT_ID: int = 100
CHILD_ID: int = 200
AUTHOR_ID: int = 1
AUTHOR_NAME: str = 'Ada Lovelace'

# 2020-09-13 12:26:40 UTC in the three shapes a timestamp reaches the model in
STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)
STAMP_STRING: str = '2020-09-13T12:26:40Z'

CREATE_CHANGES: dict[str, Any] = {'note': 'first'}


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a complete log document, with the given keys replaced"""
    document: dict[str, Any] = {
        ObjectRelationLogKey.PUBLIC_ID.value: PUBLIC_ID,
        ObjectRelationLogKey.OBJECT_RELATION_ID.value: OBJECT_RELATION_ID,
        ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value: PARENT_ID,
        ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value: CHILD_ID,
        ObjectRelationLogKey.CREATION_TIME.value: STAMP,
        ObjectRelationLogKey.ACTION.value: LogInteraction.CREATE.value,
        ObjectRelationLogKey.AUTHOR_ID.value: AUTHOR_ID,
        ObjectRelationLogKey.AUTHOR_NAME.value: AUTHOR_NAME,
        ObjectRelationLogKey.CHANGES.value: CREATE_CHANGES,
    }
    document.update(overrides)

    return document


def _stored(**overrides: Any) -> dict[str, Any]:
    """Runs a document through the model and returns what would be stored"""
    return CmdbObjectRelationLog.to_json(CmdbObjectRelationLog.from_data(_document(**overrides)))


class TestNothingIsInvented:
    """What the model does with what an entry does not carry."""

    def test_an_entry_without_a_timestamp_reports_none(self) -> None:
        """
        The constructor used to answer datetime.now() here, on every read

        On an audit trail that is the worst possible default: the entry looks freshly written, the
        value changes each time it is fetched, and nothing about it looks wrong.
        """
        document: dict[str, Any] = _document()
        document.pop(ObjectRelationLogKey.CREATION_TIME.value)

        assert CmdbObjectRelationLog.to_json(CmdbObjectRelationLog.from_data(document))[
            ObjectRelationLogKey.CREATION_TIME.value
        ] is None

    def test_a_null_timestamp_stays_null(self) -> None:
        """Same rule when the key is there and empty."""
        assert _stored(creation_time=None)[ObjectRelationLogKey.CREATION_TIME.value] is None

    def test_the_entry_is_not_rewritten_on_the_way_out(self) -> None:
        """Reading an entry twice returns the same document, which a now() default did not."""
        document: dict[str, Any] = _document()

        assert CmdbObjectRelationLog.to_json(CmdbObjectRelationLog.from_data(document)) == \
               CmdbObjectRelationLog.to_json(CmdbObjectRelationLog.from_data(document))


class TestNothingIsRefused:
    """The deliberate difference from the models swept alongside this one."""

    def test_no_required_keys_are_declared(self) -> None:
        """
        An audit entry is never refused for what it lacks

        A log outlives what it describes and may predate a key the writer added later; refusing to
        read it would hide history, which is a worse failure than showing an incomplete row.
        """
        assert CmdbObjectRelationLog.REQUIRED_INIT_KEYS == []

    def test_an_entry_carrying_only_its_ids_is_readable(self) -> None:
        """The minimum a stored entry can be, read without raising and without inventing values."""
        stored: dict[str, Any] = CmdbObjectRelationLog.to_json(CmdbObjectRelationLog.from_data({
            ObjectRelationLogKey.PUBLIC_ID.value: PUBLIC_ID,
            ObjectRelationLogKey.OBJECT_RELATION_ID.value: OBJECT_RELATION_ID,
        }))

        assert stored[ObjectRelationLogKey.ACTION.value] is None
        assert stored[ObjectRelationLogKey.AUTHOR_NAME.value] is None
        assert stored[ObjectRelationLogKey.CHANGES.value] == {}

    def test_an_entry_whose_relation_is_gone_is_still_readable(self) -> None:
        """
        Deleting a CmdbObjectRelation leaves its history behind, by design

        So a stored object_relation_id that resolves to nothing is the normal state of an old entry,
        not a broken document.
        """
        assert _stored(object_relation_id=999999)[
            ObjectRelationLogKey.OBJECT_RELATION_ID.value
        ] == 999999


class TestTheTimestamp:
    """The one value the model does refuse."""

    @pytest.mark.parametrize('shape, value', [
        ('wrapper', {'$date': STAMP_MILLIS}),
        ('string', STAMP_STRING),
        ('datetime', STAMP),
    ])
    def test_every_shape_becomes_a_real_datetime(self, shape: str, value: Any) -> None:
        """MongoDB can only sort and range-filter a real date, whichever shape wrote the entry."""
        del shape

        assert _stored(creation_time=value)[ObjectRelationLogKey.CREATION_TIME.value] == STAMP

    def test_the_timestamp_is_declared_as_a_date_field(self) -> None:
        """DATE_FIELDS is what makes a raw dict write normalise too, not only a write through the model."""
        assert CmdbObjectRelationLog.DATE_FIELDS == tuple(
            key.value for key in OBJECT_RELATION_LOG_DATE_KEYS
        )
        assert CmdbObjectRelationLog.DATE_FIELDS == (ObjectRelationLogKey.CREATION_TIME.value,)

    def test_an_unreadable_timestamp_is_refused(self) -> None:
        """
        'sometime in March 2020' used to parse into a date built from today's day number

        The one thing worth refusing on this model: a wrong date in an audit trail is indistinguishable
        from a right one.
        """
        with pytest.raises(CmdbObjectRelationLogInitFromDataError) as caught:
            CmdbObjectRelationLog.from_data(_document(creation_time='sometime in March 2020'))

        assert ObjectRelationLogKey.CREATION_TIME.value in str(caught.value)


class TestChanges:
    """The payload that says what actually happened."""

    def test_a_create_snapshot_is_kept_as_written(self) -> None:
        """A CREATE entry carries a flat {name: value} snapshot of the new field values."""
        assert _stored()[ObjectRelationLogKey.CHANGES.value] == CREATE_CHANGES

    def test_an_edit_diff_is_kept_as_written(self) -> None:
        """An EDIT entry carries the modified / added / deleted diff the manager computed."""
        diff: dict[str, Any] = {
            'modified': {'status': {'before': 'active', 'after': 'inactive'}},
            'added': {},
            'deleted': {},
        }

        assert _stored(action=LogInteraction.EDIT.value, changes=diff)[
            ObjectRelationLogKey.CHANGES.value
        ] == diff

    def test_a_missing_changes_entry_becomes_the_empty_dict(self) -> None:
        """
        One empty state, not two

        The log builder writes {} for a DELETE, while the model's own default was None - so a consumer
        had to handle both spellings of "nothing changed".
        """
        document: dict[str, Any] = _document()
        document.pop(ObjectRelationLogKey.CHANGES.value)

        assert CmdbObjectRelationLog.from_data(document).changes == {}

    def test_a_null_changes_entry_becomes_the_empty_dict(self) -> None:
        """Same rule when the key is present and null."""
        assert _stored(changes=None)[ObjectRelationLogKey.CHANGES.value] == {}

    def test_every_instance_gets_a_fresh_changes_dict(self) -> None:
        """The coerced default must not be shared between instances."""
        first = CmdbObjectRelationLog.from_data(_document(changes=None))
        second = CmdbObjectRelationLog.from_data(_document(changes=None))
        first.changes['note'] = 'x'

        assert second.changes == {}


class TestTheDocumentContract:
    """The key set and the error types."""

    def test_to_json_emits_exactly_the_key_enum(self) -> None:
        """A value set outside the enum cannot reach a response, and a removed key cannot linger."""
        assert set(_stored()) == {key.value for key in ObjectRelationLogKey}

    def test_the_key_enum_names_the_constructor_arguments(self) -> None:
        """What lets the model share CmdbDAO.from_data: every key is a parameter of that name."""
        # pylint: disable=no-member
        parameters: set[str] = set(CmdbObjectRelationLog.__init__.__code__.co_varnames)

        assert {key.value for key in ObjectRelationLogKey} <= parameters

    @pytest.mark.parametrize('action', list(LogInteraction), ids=lambda action: action.value)
    def test_every_logged_action_round_trips(self, action: LogInteraction) -> None:
        """The three interactions the audit trail records, stored as their plain string."""
        assert _stored(action=action.value)[ObjectRelationLogKey.ACTION.value] == action.value

    def test_to_json_refuses_another_models_instance(self) -> None:
        """The shared to_json type-checks its instance, so no other model serialises as a log entry."""
        with pytest.raises(CmdbObjectRelationLogToJsonError):
            CmdbObjectRelationLog.to_json(object())

    def test_to_json_of_an_instance_without_a_public_id_is_the_models_own_error(self) -> None:
        """get_public_id refuses an unassigned id, and the shared to_json wraps that."""
        instance = CmdbObjectRelationLog.from_data(_document())
        del instance.public_id

        with pytest.raises(CmdbObjectRelationLogToJsonError):
            CmdbObjectRelationLog.to_json(instance)

    def test_a_bad_public_id_surfaces_as_the_models_own_error(self) -> None:
        """The constructor's except arm: CmdbDAO casts public_id to int, and 'x' cannot be cast."""
        with pytest.raises(CmdbObjectRelationLogInitError):
            CmdbObjectRelationLog(public_id='x', object_relation_id=OBJECT_RELATION_ID)

    def test_the_constructor_cannot_be_called_positionally(self) -> None:
        """CmdbDAO.__new__ reads public_id out of **kwargs and runs first, so it never could."""
        with pytest.raises(RequiredInitKeyNotFoundError):
            CmdbObjectRelationLog(PUBLIC_ID)


class TestCollectionAndIndexes:
    """What the collection is, and which query each index answers."""

    def test_stores_in_the_framework_object_relation_logs_collection(self) -> None:
        """The collection name is what the object-relation routes purge and read through."""
        assert CmdbObjectRelationLog.COLLECTION == 'framework.objectRelationLogs'

    def test_reaches_the_collection_validator_through_the_framework_registry(self) -> None:
        """A model in no registry has no collection created and therefore no index built."""
        assert CmdbObjectRelationLog in FRAMEWORK_COLLECTIONS

    @pytest.mark.parametrize('index_name, side_key', [
        ('object_relation_parent_history', ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value),
        ('object_relation_child_history', ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value),
    ])
    def test_each_side_of_the_history_query_has_a_compound_index(
        self, index_name: str, side_key: str,
    ) -> None:
        """
        The object view matches on either endpoint and sorts by public_id

        Before this the collection carried one index on a key nothing queries, so the only query it
        ever serves scanned an unbounded, append-only collection.
        """
        index = next(
            index for index in CmdbObjectRelationLog.get_index_keys()
            if index.document['name'] == index_name
        )

        assert [key for key, _direction in index.document['key'].items()] == [
            side_key,
            ObjectRelationLogKey.PUBLIC_ID.value,
        ]

    def test_the_relation_index_is_kept_for_the_delete_route(self) -> None:
        """
        No query uses it today; it is kept because the delete route addresses entries by relation

        Recorded as a test so that dropping it stays a decision rather than a cleanup.
        """
        index_names: set[str] = {
            index.document['name'] for index in CmdbObjectRelationLog.get_index_keys()
        }

        assert ObjectRelationLogKey.OBJECT_RELATION_ID.value in index_names

    def test_keeps_the_inherited_unique_public_id_index(self) -> None:
        """The identity index every CmdbDAO gets; declaring INDEX_KEYS must not displace it."""
        public_id_indexes = [
            index for index in CmdbObjectRelationLog.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        ]

        assert len(public_id_indexes) == 1
        assert public_id_indexes[0].document['unique'] is True

    def test_every_declared_index_states_whether_it_is_unique(self) -> None:
        """The house convention, and the one thing an index declaration must not leave to a default."""
        for index in CmdbObjectRelationLog.get_index_keys():
            assert 'unique' in index.document

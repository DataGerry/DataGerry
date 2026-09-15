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
Unit tests for cmdb.models.object_relation_model

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains its own:

  - **both timestamps end up as real datetimes**, from any of the three shapes a date arrives in. The
    ``{'$date': ...}`` wrapper used to be stored verbatim in ``last_edit_time`` - the create route left
    that key to the body and nothing normalised it - so one collection held two different types for its
    two date keys and MongoDB could sort neither the wrapper nor a tab ordered by it
  - **an unreadable timestamp is refused, not guessed.** The previous implementation parsed strings
    with ``fuzzy=True``, which reads 'sometime in March 2020' as a real date built from today's day
    number
  - **a document without a creation time reports None**, where the constructor used to invent
    ``datetime.now()`` on every read - so a legacy document's creation date changed each time it was
    fetched
  - the two compound tab indexes, which are what make a relation tab's match and sort one index lookup
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from cerberus import Validator

from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_COLLECTIONS
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.object_relation_model import (
    CmdbObjectRelation,
    OBJECT_RELATION_DATE_KEYS,
    ObjectRelationFieldValueKey,
    ObjectRelationKey,
)
from cmdb.class_schema.object_relation_model.cmdb_object_relation_schema import (
    get_cmdb_object_relation_schema,
)
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.cmdb_object_relation import (
    CmdbObjectRelationInitError,
    CmdbObjectRelationInitFromDataError,
    CmdbObjectRelationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 21
RELATION_ID: int = 5
PARENT_ID: int = 100
PARENT_TYPE_ID: int = 3
CHILD_ID: int = 200
CHILD_TYPE_ID: int = 4
AUTHOR_ID: int = 1

# 2020-09-13 12:26:40 UTC in the three shapes a timestamp reaches the model in
STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)
STAMP_STRING: str = '2020-09-13T12:26:40Z'


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a complete CmdbObjectRelation document, with the given keys replaced"""
    document: dict[str, Any] = {
        ObjectRelationKey.PUBLIC_ID.value: PUBLIC_ID,
        ObjectRelationKey.RELATION_ID.value: RELATION_ID,
        ObjectRelationKey.RELATION_PARENT_ID.value: PARENT_ID,
        ObjectRelationKey.RELATION_PARENT_TYPE_ID.value: PARENT_TYPE_ID,
        ObjectRelationKey.RELATION_CHILD_ID.value: CHILD_ID,
        ObjectRelationKey.RELATION_CHILD_TYPE_ID.value: CHILD_TYPE_ID,
        ObjectRelationKey.AUTHOR_ID.value: AUTHOR_ID,
        ObjectRelationKey.CREATION_TIME.value: STAMP,
        ObjectRelationKey.LAST_EDIT_TIME.value: None,
        ObjectRelationKey.FIELD_VALUES.value: [
            {ObjectRelationFieldValueKey.NAME.value: 'note', ObjectRelationFieldValueKey.VALUE.value: 'x'},
        ],
    }
    document.update(overrides)

    return document


def _stored(**overrides: Any) -> dict[str, Any]:
    """Runs a document through the model and returns what would be stored"""
    return CmdbObjectRelation.to_json(CmdbObjectRelation.from_data(_document(**overrides)))


class TestTimestampsBecomeRealDates:
    """The defect this sweep was scheduled for, pinned from the model's side."""

    @pytest.mark.parametrize('shape, value', [
        ('wrapper', {'$date': STAMP_MILLIS}),
        ('string', STAMP_STRING),
        ('datetime', STAMP),
    ])
    def test_every_shape_of_last_edit_time_is_stored_as_a_datetime(self, shape: str, value: Any) -> None:
        """
        The wrapper is the shape the frontend sends, and it used to be stored as a sub-document

        MongoDB cannot sort or range-filter that, and the relation-tab route lets a client sort by this
        very key - which then ordered by BSON type instead of by time.
        """
        del shape

        assert _stored(last_edit_time=value)[ObjectRelationKey.LAST_EDIT_TIME.value] == STAMP

    @pytest.mark.parametrize('shape, value', [
        ('wrapper', {'$date': STAMP_MILLIS}),
        ('string', STAMP_STRING),
        ('datetime', STAMP),
    ])
    def test_every_shape_of_creation_time_is_stored_as_a_datetime(self, shape: str, value: Any) -> None:
        """The key that was always a real date keeps being one, from any shape."""
        del shape

        assert _stored(creation_time=value)[ObjectRelationKey.CREATION_TIME.value] == STAMP

    def test_both_timestamps_are_declared_as_date_fields(self) -> None:
        """
        DATE_FIELDS is what makes a raw dict write normalise too, not only a write through the model

        GenericManager reads it on insert / bulk insert / update, which is the path the create route
        takes - it hands the validated payload straight to insert_item.
        """
        assert CmdbObjectRelation.DATE_FIELDS == tuple(key.value for key in OBJECT_RELATION_DATE_KEYS)
        assert set(CmdbObjectRelation.DATE_FIELDS) == {
            ObjectRelationKey.CREATION_TIME.value,
            ObjectRelationKey.LAST_EDIT_TIME.value,
        }

    def test_a_null_timestamp_stays_null(self) -> None:
        """'Never edited' is a real state and must not become a date."""
        assert _stored(last_edit_time=None)[ObjectRelationKey.LAST_EDIT_TIME.value] is None

    def test_an_empty_wrapper_is_read_as_no_date(self) -> None:
        """An emptied date widget means "no date", not a broken one."""
        assert _stored(last_edit_time={})[ObjectRelationKey.LAST_EDIT_TIME.value] is None

    def test_an_unreadable_timestamp_is_refused(self) -> None:
        """
        The fuzzy parser used to turn a note into a date built from today's day number

        Refusing is the only safe answer: nothing about a wrong date looks wrong afterwards.
        """
        with pytest.raises(CmdbObjectRelationInitFromDataError) as caught:
            CmdbObjectRelation.from_data(_document(last_edit_time='sometime in March 2020'))

        assert ObjectRelationKey.LAST_EDIT_TIME.value in str(caught.value)

    def test_the_document_is_normalised_in_place(self) -> None:
        """
        normalize_document is public because a caller writing a raw dict needs it too

        GenericManager runs it on every dict write, so the payload it inserts is already normalised.
        """
        document: dict[str, Any] = _document(last_edit_time={'$date': STAMP_MILLIS})

        CmdbObjectRelation.normalize_document(document)

        assert document[ObjectRelationKey.LAST_EDIT_TIME.value] == STAMP


class TestNoValueIsInvented:
    """What the model does with what a document does not carry."""

    def test_a_document_without_a_creation_time_reports_none(self) -> None:
        """
        The constructor used to default to datetime.now(), on every read

        A document written before the create route stamped the key therefore reported *today* as its
        creation date, and a different value each time it was fetched. None says what is true: this
        document does not carry one.
        """
        document: dict[str, Any] = _document()
        document.pop(ObjectRelationKey.CREATION_TIME.value)

        assert CmdbObjectRelation.to_json(CmdbObjectRelation.from_data(document))[
            ObjectRelationKey.CREATION_TIME.value
        ] is None

    def test_absent_field_values_become_an_empty_list(self) -> None:
        """A relation with no field values is normal; a null there is not."""
        document: dict[str, Any] = _document()
        document.pop(ObjectRelationKey.FIELD_VALUES.value)

        assert _stored(**{ObjectRelationKey.FIELD_VALUES.value: None})[
            ObjectRelationKey.FIELD_VALUES.value
        ] == []
        assert CmdbObjectRelation.from_data(document).field_values == []

    def test_every_instance_gets_a_fresh_field_values_list(self) -> None:
        """The coerced default must not be shared between instances."""
        first = CmdbObjectRelation.from_data(_document(field_values=None))
        second = CmdbObjectRelation.from_data(_document(field_values=None))
        first.field_values.append({'name': 'n', 'value': 'v'})

        assert second.field_values == []


class TestTheDocumentContract:
    """The key set, and what a document must carry to be readable."""

    def test_to_json_emits_exactly_the_key_enum(self) -> None:
        """A value set outside the enum cannot reach a response, and a removed key cannot linger."""
        assert set(_stored()) == {key.value for key in ObjectRelationKey}

    def test_the_key_enum_names_the_constructor_arguments(self) -> None:
        """What lets the model share CmdbDAO.from_data: every key is a parameter of that name."""
        # pylint: disable=no-member
        parameters: set[str] = set(CmdbObjectRelation.__init__.__code__.co_varnames)

        assert {key.value for key in ObjectRelationKey} <= parameters

    def test_the_schema_is_built_from_the_key_enum(self) -> None:
        """A key renamed in the enum cannot leave the schema validating the old spelling."""
        assert set(get_cmdb_object_relation_schema()) == {key.value for key in ObjectRelationKey}

    def test_a_stored_document_passes_its_own_schema(self) -> None:
        """
        GET then an unmodified PUT, which is what every DataGerry write route expects

        The datetime the model stores is one of the three shapes the schema accepts, so the round trip
        holds without the response having to be re-shaped.
        """
        validator = Validator(get_cmdb_object_relation_schema())
        document: dict[str, Any] = _stored()

        assert validator.validate(document), validator.errors

    @pytest.mark.parametrize('required_key', CmdbObjectRelation.REQUIRED_INIT_KEYS)
    def test_a_document_missing_a_required_key_is_refused(self, required_key: str) -> None:
        """
        A relation missing an endpoint or its definition describes nothing at all

        Refusing here names the document and the key; reading it as a half-built instance moves the
        failure somewhere that knows neither.
        """
        document: dict[str, Any] = _document()
        document.pop(required_key)

        with pytest.raises(CmdbObjectRelationInitFromDataError) as caught:
            CmdbObjectRelation.from_data(document)

        assert required_key in str(caught.value)

    def test_the_required_keys_are_the_schema_required_ones(self) -> None:
        """The model and the schema have to refuse the same documents."""
        schema: dict[str, Any] = get_cmdb_object_relation_schema()
        schema_required: set[str] = {key for key, rules in schema.items() if rules.get('required')}

        assert set(CmdbObjectRelation.REQUIRED_INIT_KEYS) == schema_required

    def test_to_json_refuses_another_models_instance(self) -> None:
        """The shared to_json type-checks its instance, so no other model serialises as this one."""
        with pytest.raises(CmdbObjectRelationToJsonError):
            CmdbObjectRelation.to_json(object())

    def test_to_json_of_an_instance_without_a_public_id_is_the_models_own_error(self) -> None:
        """get_public_id refuses an unassigned id, and the shared to_json wraps that."""
        instance = CmdbObjectRelation.from_data(_document())
        del instance.public_id

        with pytest.raises(CmdbObjectRelationToJsonError):
            CmdbObjectRelation.to_json(instance)

    def test_a_bad_public_id_surfaces_as_the_models_own_error(self) -> None:
        """The constructor's except arm: CmdbDAO casts public_id to int, and 'x' cannot be cast."""
        with pytest.raises(CmdbObjectRelationInitError):
            CmdbObjectRelation(
                public_id='x',
                relation_id=RELATION_ID,
                relation_parent_id=PARENT_ID,
                relation_parent_type_id=PARENT_TYPE_ID,
                relation_child_id=CHILD_ID,
                relation_child_type_id=CHILD_TYPE_ID,
            )

    def test_the_constructor_cannot_be_called_positionally(self) -> None:
        """CmdbDAO.__new__ reads public_id out of **kwargs and runs first, so it never could."""
        with pytest.raises(RequiredInitKeyNotFoundError):
            CmdbObjectRelation(PUBLIC_ID)


class TestCollectionAndIndexes:
    """What the collection is, and which queries an index answers."""

    def test_stores_in_the_framework_object_relations_collection(self) -> None:
        """The collection name is part of every cascade that writes it from another manager."""
        assert CmdbObjectRelation.COLLECTION == 'framework.objectRelations'

    def test_reaches_the_collection_validator_through_the_framework_registry(self) -> None:
        """A model in no registry has no collection created and therefore no index built."""
        assert CmdbObjectRelation in FRAMEWORK_COLLECTIONS

    def test_indexes_every_key_a_cascade_filters_on(self) -> None:
        """Deleting an object, a type or a relation definition filters on one of these five."""
        index_names: set[str] = {index.document['name'] for index in CmdbObjectRelation.get_index_keys()}

        assert {
            ObjectRelationKey.RELATION_ID.value,
            ObjectRelationKey.RELATION_PARENT_ID.value,
            ObjectRelationKey.RELATION_PARENT_TYPE_ID.value,
            ObjectRelationKey.RELATION_CHILD_ID.value,
            ObjectRelationKey.RELATION_CHILD_TYPE_ID.value,
        } <= index_names

    @pytest.mark.parametrize('index_name, side_key', [
        ('relation_parent_tab', ObjectRelationKey.RELATION_PARENT_ID.value),
        ('relation_child_tab', ObjectRelationKey.RELATION_CHILD_ID.value),
    ])
    def test_each_tab_is_served_by_one_compound_index(self, index_name: str, side_key: str) -> None:
        """
        Match on (relation_id, side) and sort by public_id, from a single index

        With only the single-field indexes MongoDB matches from one of them and then sorts the whole
        group in memory, which is what these two exist to avoid.
        """
        index = next(
            index for index in CmdbObjectRelation.get_index_keys()
            if index.document['name'] == index_name
        )

        assert [key for key, _direction in index.document['key'].items()] == [
            ObjectRelationKey.RELATION_ID.value,
            side_key,
            ObjectRelationKey.PUBLIC_ID.value,
        ]

    def test_keeps_the_inherited_unique_public_id_index(self) -> None:
        """The identity index every CmdbDAO gets; declaring INDEX_KEYS must not displace it."""
        public_id_indexes = [
            index for index in CmdbObjectRelation.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        ]

        assert len(public_id_indexes) == 1
        assert public_id_indexes[0].document['unique'] is True

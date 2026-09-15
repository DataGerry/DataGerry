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
Unit tests for cmdb.models.object_model.cmdb_object

Pure tests: no Mongo, no Flask. The two sibling modules cover the standalone helper
(``extract_field_value``) and the index declarations; this one covers the model class itself, which
had no test of its own although every read, write, import, export, render and history entry in the
framework passes through it.

The model declares ``KEYS`` and inherits ``from_data`` / ``to_json`` from CmdbDAO
(tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is pinned here is
what remains its own:

  - **nothing is invented**: an object without a creation time reads as None, where the constructor
    used to answer ``datetime.now()`` - a different value on every read
  - **nothing that was readable becomes unreadable**: only ``type_id`` and ``author_id`` are required,
    the two keys the previous implementation already read with ``data['key']``. The keys the schema
    defaults (fields, multi_data_sections, active, version) are defaulted here too, in the hook
    rather than on the signature - the shared from_data passes every key explicitly, so a signature
    default never runs
  - **an unreadable timestamp is refused, not guessed** (it was parsed with ``fuzzy=True``)
  - **``get_value`` raises and its helper twin does not**, deliberately: the renderer depends on the
    raise to fall back to a type default
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_COLLECTIONS
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    OBJECT_DATE_KEYS,
    extract_field_value,
)
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.cmdb_object import (
    CmdbObjectInitError,
    CmdbObjectInitFromDataError,
    CmdbObjectToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 15
TYPE_ID: int = 3
AUTHOR_ID: int = 1

# 2020-09-13 12:26:40 UTC in the three shapes a timestamp reaches the model in
STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)
STAMP_STRING: str = '2020-09-13T12:26:40Z'

NAME_FIELD: dict[str, Any] = {
    CmdbObjectFieldKey.NAME.value: 'hostname',
    CmdbObjectFieldKey.VALUE.value: 'srv-01',
    CmdbObjectFieldKey.TYPE.value: FieldType.TEXT.value,
}


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a complete CmdbObject document, with the given keys replaced"""
    document: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID.value: PUBLIC_ID,
        CmdbObjectKey.TYPE_ID.value: TYPE_ID,
        CmdbObjectKey.AUTHOR_ID.value: AUTHOR_ID,
        CmdbObjectKey.FIELDS.value: [dict(NAME_FIELD)],
        CmdbObjectKey.ACTIVE.value: True,
        CmdbObjectKey.VERSION.value: '1.0.0',
        CmdbObjectKey.CREATION_TIME.value: STAMP,
        CmdbObjectKey.LAST_EDIT_TIME.value: None,
        CmdbObjectKey.EDITOR_ID.value: None,
        CmdbObjectKey.SPECIAL_TYPE.value: None,
        CmdbObjectKey.CI_EXPLORER_TOOLTIP.value: None,
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: [],
    }
    document.update(overrides)

    return document


def _stored(**overrides: Any) -> dict[str, Any]:
    """Runs a document through the model and returns what would be stored"""
    return CmdbObject.to_json(CmdbObject.from_data(_document(**overrides)))


def _mds_section(field_type: str) -> dict[str, Any]:
    """Builds one MDS section carrying a single row with one field of the given type"""
    return {
        CmdbObjectMdsKey.SECTION_ID.value: 'extra',
        CmdbObjectMdsKey.HIGHEST_ID.value: 1,
        CmdbObjectMdsKey.VALUES.value: [{
            CmdbObjectMdsRowKey.MULTI_DATA_ID.value: 1,
            CmdbObjectMdsRowKey.DATA.value: [{
                CmdbObjectFieldKey.NAME.value: 'nested',
                CmdbObjectFieldKey.VALUE.value: 'x',
                CmdbObjectFieldKey.TYPE.value: field_type,
            }],
        }],
    }


class TestNothingIsInvented:
    """What the model does with what a document does not carry."""

    def test_an_object_without_a_creation_time_reports_none(self) -> None:
        """
        The constructor used to answer datetime.now(), evaluated per call

        So an old document reported *today* as its creation date, and a different value each time it
        was fetched - on the collection whose history the whole audit trail hangs off.
        """
        document: dict[str, Any] = _document()
        document.pop(CmdbObjectKey.CREATION_TIME.value)

        assert CmdbObject.to_json(CmdbObject.from_data(document))[
            CmdbObjectKey.CREATION_TIME.value
        ] is None

    def test_reading_the_same_document_twice_gives_the_same_object(self) -> None:
        """A now() default made this false, which is the property that made it a defect."""
        document: dict[str, Any] = _document()
        document.pop(CmdbObjectKey.CREATION_TIME.value)

        assert CmdbObject.to_json(CmdbObject.from_data(document)) == \
               CmdbObject.to_json(CmdbObject.from_data(document))


class TestTheSchemaDefaultsApply:
    """The keys a document may omit, and what they become."""

    def test_an_absent_field_list_becomes_empty(self) -> None:
        """
        The schema declares fields required WITH a default of [], i.e. absent means empty

        Refusing such a document instead would make objects unreadable that this model has always
        read - and on this collection that is a whole database's object list.
        """
        document: dict[str, Any] = _document()
        document.pop(CmdbObjectKey.FIELDS.value)

        assert CmdbObject.from_data(document).fields == []

    def test_an_absent_mds_list_becomes_empty(self) -> None:
        """Most objects have no multi-data sections at all."""
        document: dict[str, Any] = _document()
        document.pop(CmdbObjectKey.MULTI_DATA_SECTIONS.value)

        assert CmdbObject.from_data(document).multi_data_sections == []

    def test_an_absent_active_flag_defaults_to_true(self) -> None:
        """
        The default lives in normalize_document, not on the signature

        The shared from_data passes every key explicitly, so a document without 'active' hands the
        constructor None and a signature default would never run.
        """
        document: dict[str, Any] = _document()
        document.pop(CmdbObjectKey.ACTIVE.value)

        assert CmdbObject.from_data(document).active is True

    def test_an_explicit_inactive_flag_is_kept(self) -> None:
        """Only a missing or null value is defaulted - False is an answer, not an absence."""
        assert CmdbObject.from_data(_document(active=False)).active is False

    def test_an_absent_version_defaults_to_the_class_constant(self) -> None:
        """
        DEFAULT_VERSION was declared and then not used here, while objects_helper used it

        The signature default it duplicated could never run either, because 'version' was in
        REQUIRED_INIT_KEYS and CmdbDAO.__new__ demands those as kwargs before __init__ is entered.
        """
        document: dict[str, Any] = _document()
        document.pop(CmdbObjectKey.VERSION.value)

        assert CmdbObject.from_data(document).version == CmdbObject.DEFAULT_VERSION


class TestTheTimestamps:
    """Both are server-owned, and both end up as real dates."""

    @pytest.mark.parametrize('shape, value', [
        ('wrapper', {'$date': STAMP_MILLIS}),
        ('string', STAMP_STRING),
        ('datetime', STAMP),
    ])
    def test_every_shape_of_creation_time_becomes_a_datetime(self, shape: str, value: Any) -> None:
        """The wrapper is what the frontend sends; a string is what an API client sends."""
        del shape

        assert _stored(creation_time=value)[CmdbObjectKey.CREATION_TIME.value] == STAMP

    @pytest.mark.parametrize('shape, value', [
        ('wrapper', {'$date': STAMP_MILLIS}),
        ('string', STAMP_STRING),
        ('datetime', STAMP),
    ])
    def test_every_shape_of_last_edit_time_becomes_a_datetime(self, shape: str, value: Any) -> None:
        """Same rule for the edit timestamp."""
        del shape

        assert _stored(last_edit_time=value)[CmdbObjectKey.LAST_EDIT_TIME.value] == STAMP

    def test_both_timestamps_are_declared_as_date_fields(self) -> None:
        """DATE_FIELDS is what makes a raw dict write normalise too, not only a write through here."""
        assert CmdbObject.DATE_FIELDS == tuple(key.value for key in OBJECT_DATE_KEYS)
        assert set(CmdbObject.DATE_FIELDS) == {
            CmdbObjectKey.CREATION_TIME.value,
            CmdbObjectKey.LAST_EDIT_TIME.value,
        }

    def test_an_unreadable_timestamp_is_refused(self) -> None:
        """
        'sometime in March 2020' used to parse into a date built from today's day number

        No write route can reach it today - create stamps, update pins, PATCH refuses and the importer
        forces - but the model is called directly by the search pipeline and by integrations.
        """
        with pytest.raises(CmdbObjectInitFromDataError) as caught:
            CmdbObject.from_data(_document(creation_time='sometime in March 2020'))

        assert CmdbObjectKey.CREATION_TIME.value in str(caught.value)

    def test_a_null_timestamp_stays_null(self) -> None:
        """'Never edited' is a real state."""
        assert _stored(last_edit_time=None)[CmdbObjectKey.LAST_EDIT_TIME.value] is None


class TestTheDocumentContract:
    """The key set, the required keys and the coercions."""

    def test_to_json_emits_exactly_the_key_enum(self) -> None:
        """A value set outside the enum cannot reach a response, and a removed key cannot linger."""
        assert set(_stored()) == {key.value for key in CmdbObjectKey}

    def test_the_key_enum_names_the_constructor_arguments(self) -> None:
        """What lets the model share CmdbDAO.from_data: every key is a parameter of that name."""
        # pylint: disable=no-member
        parameters: set[str] = set(CmdbObject.__init__.__code__.co_varnames)

        assert {key.value for key in CmdbObjectKey} <= parameters

    def test_an_unknown_key_is_ignored_rather_than_stored(self) -> None:
        """
        The constructor used to take **kwargs and setattr whatever a document carried

        A drifted or misspelled key became a silent attribute that to_json then dropped. It is also
        what lets the transient 'location_name' of a create payload pass through harmlessly.
        """
        stored: dict[str, Any] = _stored(location_name='Rack 4', typo_key='whatever')

        assert 'location_name' not in stored
        assert 'typo_key' not in stored

    @pytest.mark.parametrize('required_key', CmdbObject.REQUIRED_INIT_KEYS)
    def test_a_document_missing_a_required_key_is_refused(self, required_key: str) -> None:
        """
        Both were already mandatory: the previous from_data read them with data['key'] and int()

        An object without a type or an owner describes nothing, so this is a refusal rather than a
        default.
        """
        document: dict[str, Any] = _document()
        document.pop(required_key)

        with pytest.raises(CmdbObjectInitFromDataError) as caught:
            CmdbObject.from_data(document)

        assert required_key in str(caught.value)

    def test_only_the_type_and_the_author_are_required(self) -> None:
        """
        Declaring more would make documents unreadable that have always been read

        Pinned as a decision: the other keys the list used to name are optional in the schema and
        defaulted in the hook.
        """
        assert set(CmdbObject.REQUIRED_INIT_KEYS) == {
            CmdbObjectKey.TYPE_ID.value,
            CmdbObjectKey.AUTHOR_ID.value,
        }

    def test_the_type_and_author_ids_are_coerced_to_integers(self) -> None:
        """
        A document storing them as strings still reads, as it did before the migration

        int() in the constructor is what keeps that true now that from_data no longer coerces.
        """
        instance = CmdbObject.from_data(_document(type_id='7', author_id='9'))

        assert instance.type_id == 7
        assert instance.author_id == 9

    def test_an_uncoercible_type_id_surfaces_as_the_models_own_error(self) -> None:
        """The constructor's except arm."""
        with pytest.raises(CmdbObjectInitFromDataError):
            CmdbObject.from_data(_document(type_id='not-a-number'))

    def test_a_bad_public_id_surfaces_as_the_models_own_error(self) -> None:
        """CmdbDAO casts public_id to int, and 'x' cannot be cast."""
        with pytest.raises(CmdbObjectInitError):
            CmdbObject(public_id='x', type_id=TYPE_ID, author_id=AUTHOR_ID, fields=[])

    def test_to_json_refuses_another_models_instance(self) -> None:
        """The shared to_json type-checks its instance, so nothing else serialises as an object."""
        with pytest.raises(CmdbObjectToJsonError):
            CmdbObject.to_json(object())

    def test_the_constructor_cannot_be_called_positionally(self) -> None:
        """CmdbDAO.__new__ reads public_id out of **kwargs and runs first, so it never could."""
        with pytest.raises(RequiredInitKeyNotFoundError):
            CmdbObject(PUBLIC_ID)


class TestGetValue:
    """The accessor the renderer depends on, and its deliberate difference from the helper."""

    def test_returns_the_value_of_a_named_field(self) -> None:
        """The ordinary case."""
        assert CmdbObject.from_data(_document()).get_value('hostname') == 'srv-01'

    def test_returns_a_stored_none_rather_than_raising(self) -> None:
        """
        A field that exists and holds nothing is a different answer from a field that is absent

        Which is exactly why the absent case raises: the renderer has to tell them apart.
        """
        empty_field: dict[str, Any] = {**NAME_FIELD, CmdbObjectFieldKey.VALUE.value: None}

        assert CmdbObject.from_data(_document(fields=[empty_field])).get_value('hostname') is None

    def test_raises_for_a_field_the_object_does_not_carry(self) -> None:
        """
        Load-bearing: the renderer catches this to fall back to the type's default

        A summary field a type declares but an older object never stored would otherwise render as an
        empty value instead of the default.
        """
        with pytest.raises(ValueError):
            CmdbObject.from_data(_document()).get_value('missing')

    def test_the_helper_twin_answers_none_for_the_same_question(self) -> None:
        """
        Two readers, opposite failure modes, both live and both deliberate

        Pinned together so the divergence stays a decision: extract_field_value serves callers reading
        raw documents, get_value serves the renderer.
        """
        assert extract_field_value(_document(), 'missing') is None


class TestHasFieldsOfType:
    """The guard behind the location sync and the select-option propagation."""

    def test_finds_a_top_level_field_of_the_type(self) -> None:
        """The common case: a field declared directly on the object."""
        location_field: dict[str, Any] = {
            **NAME_FIELD, CmdbObjectFieldKey.TYPE.value: FieldType.LOCATION.value,
        }

        assert CmdbObject.from_data(_document(fields=[location_field])).has_fields_of_type(
            FieldType.LOCATION,
        ) is True

    def test_finds_a_field_nested_in_a_multi_data_section(self) -> None:
        """
        An MDS row's fields count too, which is what the callers mean by 'has one'

        A select field inside a section still needs its options propagated.
        """
        instance = CmdbObject.from_data(_document(
            fields=[], multi_data_sections=[_mds_section(FieldType.SELECT.value)],
        ))

        assert instance.has_fields_of_type(FieldType.SELECT) is True

    def test_answers_false_when_neither_place_holds_one(self) -> None:
        """The fall-through both loops reach, and the answer the guards act on most often."""
        instance = CmdbObject.from_data(_document(
            multi_data_sections=[_mds_section(FieldType.TEXT.value)],
        ))

        assert instance.has_fields_of_type(FieldType.LOCATION) is False

    def test_an_object_with_no_fields_at_all_answers_false(self) -> None:
        """Neither list is iterated, and nothing raises."""
        assert CmdbObject.from_data(_document(fields=[], multi_data_sections=[])).has_fields_of_type(
            FieldType.TEXT,
        ) is False

    def test_a_section_without_rows_is_skipped(self) -> None:
        """A section container added before its first row is a normal, empty state."""
        empty_section: dict[str, Any] = {
            CmdbObjectMdsKey.SECTION_ID.value: 'extra',
            CmdbObjectMdsKey.HIGHEST_ID.value: 0,
        }

        instance = CmdbObject.from_data(_document(fields=[], multi_data_sections=[empty_section]))

        assert instance.has_fields_of_type(FieldType.TEXT) is False


class TestFieldDiff:
    """The '/' operator, kept as public model API."""

    def test_reports_what_each_side_alone_carries(self) -> None:
        """A changed value appears on both sides: once as it was, once as it is."""
        before = CmdbObject.from_data(_document())
        after = CmdbObject.from_data(_document(fields=[
            {**NAME_FIELD, CmdbObjectFieldKey.VALUE.value: 'srv-02'},
        ]))

        difference = before / after

        assert difference['old'] == [NAME_FIELD]
        assert difference['new'] == [{**NAME_FIELD, CmdbObjectFieldKey.VALUE.value: 'srv-02'}]

    def test_two_equal_objects_differ_in_nothing(self) -> None:
        """Entries are compared whole, so identical lists cancel out."""
        difference = CmdbObject.from_data(_document()) / CmdbObject.from_data(_document())

        assert difference == {'old': [], 'new': []}

    def test_comparing_with_anything_else_is_a_type_error(self) -> None:
        """The operator is only defined between two CmdbObjects."""
        with pytest.raises(TypeError):
            CmdbObject.from_data(_document()) / 'not an object'


class TestCollectionAndIndexes:
    """What the collection is, and which queries an index answers."""

    def test_stores_in_the_framework_objects_collection(self) -> None:
        """The collection name every manager and migration in the framework addresses."""
        assert CmdbObject.COLLECTION == 'framework.objects'

    def test_reaches_the_collection_validator_through_the_framework_registry(self) -> None:
        """A model in no registry has no collection created and therefore no index built."""
        assert CmdbObject in FRAMEWORK_COLLECTIONS

    def test_the_index_paths_are_built_from_the_key_enums(self) -> None:
        """
        A renamed key cannot leave an index pointing at a path that no longer exists

        The five declarations used to spell their dotted paths as literals.
        """
        index_paths: set[str] = {
            key for index in CmdbObject.get_index_keys() for key in index.document['key']
        }

        assert f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.VALUE.value}' in index_paths
        assert (
            f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.VALUES.value}'
            f'.{CmdbObjectMdsRowKey.DATA.value}.{CmdbObjectFieldKey.NAME.value}'
        ) in index_paths

    def test_keeps_the_inherited_unique_public_id_index(self) -> None:
        """The identity index every CmdbDAO gets; declaring INDEX_KEYS must not displace it."""
        public_id_indexes = [
            index for index in CmdbObject.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        ]

        assert len(public_id_indexes) == 1
        assert public_id_indexes[0].document['unique'] is True

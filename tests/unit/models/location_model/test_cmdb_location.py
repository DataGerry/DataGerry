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
Unit tests for cmdb.models.location_model.cmdb_location

The class that owns the ``framework.locations`` document had **no test module of its own** until
2026-09-10 - it was exercised through the manager, the routes and the functional suite, which is why
its three hand-rolled `except` arms were its only uncovered statements.

Those three methods are gone: the model declares ``KEYS`` and shares ``CmdbDAO.from_data`` /
``to_json``. What is pinned here is the behaviour the migration must preserve and the strictness it
adds:

* the round trip and its key order - the eight keys are a frontend contract (``LocationTreeNode``);
* ``REQUIRED_INIT_KEYS`` actually refusing a document that misses one of the five. It used to be
  **inert on the read path**: ``CmdbDAO.__new__`` only checks that the keyword was passed, and the
  old ``from_data`` always passed all eight, so a document without a ``name`` became an instance
  holding None and the list routes answered ``"name": null``;
* the two optional render keys defaulting for an absent **and** a null value, since they are copied
  from the CmdbType at write time and a stored null used to reach the tree as one;
* ``to_json`` refusing a foreign instance - ``LocationNode`` carries five of the same attributes.
"""
from typing import Any

import pytest
from pymongo import IndexModel

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import (
    CmdbLocationDefault,
    LocationKey,
    RootLocationDefault,
)

from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.cmdb_location import (
    CmdbLocationInitError,
    CmdbLocationInitFromDataError,
    CmdbLocationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 21
NAME: str = 'Room 42'
PARENT_ID: int = 4
OBJECT_ID: int = 88
TYPE_ID: int = 12
TYPE_LABEL: str = 'Room'
TYPE_ICON: str = 'fas fa-door-open'


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored CmdbLocation document, as the manager reads it."""
    document: dict[str, Any] = {
        LocationKey.PUBLIC_ID.value: PUBLIC_ID,
        LocationKey.NAME.value: NAME,
        LocationKey.PARENT.value: PARENT_ID,
        LocationKey.OBJECT_ID.value: OBJECT_ID,
        LocationKey.TYPE_ID.value: TYPE_ID,
        LocationKey.TYPE_LABEL.value: TYPE_LABEL,
        LocationKey.TYPE_ICON.value: TYPE_ICON,
        LocationKey.TYPE_SELECTABLE.value: True,
    }
    document.update(overrides)

    return document


def _location(**overrides: Any) -> CmdbLocation:
    """A CmdbLocation built from a stored document."""
    return CmdbLocation.from_data(_document(**overrides))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the class contract                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheClassContract:
    """What the collection, the shared serialisation and index reconciliation read off the class."""

    def test_the_collection_is_the_location_collection(self) -> None:
        """Every manager, updater and graph lookup resolves the name from here"""
        assert CmdbLocation.COLLECTION == 'framework.locations'

    def test_the_key_enum_drives_the_shared_serialisation(self) -> None:
        """KEYS is what lets the model share from_data / to_json instead of implementing them"""
        assert CmdbLocation.KEYS is LocationKey
        assert 'from_data' not in vars(CmdbLocation)
        assert 'to_json' not in vars(CmdbLocation)

    def test_the_typed_errors_are_declared(self) -> None:
        """The shared implementation raises the model's own errors, not a generic one"""
        assert CmdbLocation.INIT_FROM_DATA_ERROR is CmdbLocationInitFromDataError
        assert CmdbLocation.TO_JSON_ERROR is CmdbLocationToJsonError

    def test_the_five_keys_a_node_needs_are_required(self) -> None:
        """Without them the document names no tree edge and nothing to render"""
        assert CmdbLocation.REQUIRED_INIT_KEYS == [
            LocationKey.NAME.value,
            LocationKey.PARENT.value,
            LocationKey.OBJECT_ID.value,
            LocationKey.TYPE_ID.value,
            LocationKey.TYPE_LABEL.value,
        ]

    def test_the_object_id_index_is_unique(self) -> None:
        """A CmdbObject owns at most one node, which every object-driven read relies on"""
        object_id_index = next(
            index for index in CmdbLocation.INDEX_KEYS if index['name'] == LocationKey.OBJECT_ID.value
        )

        assert object_id_index['unique'] is True
        assert [key for key, _ in object_id_index['keys']] == [LocationKey.OBJECT_ID.value]

    def test_the_tree_walk_indexes_are_not_unique(self) -> None:
        """Many nodes share a parent and a type - only the object link is exclusive"""
        for name in (LocationKey.PARENT.value, LocationKey.TYPE_ID.value):
            declaration = next(index for index in CmdbLocation.INDEX_KEYS if index['name'] == name)

            assert declaration['unique'] is False

    def test_the_declared_indexes_are_buildable(self) -> None:
        """CollectionValidator builds these, so a malformed declaration breaks the first boot"""
        indexes = CmdbLocation.get_index_keys()

        assert all(isinstance(index, IndexModel) for index in indexes)
        assert {LocationKey.OBJECT_ID.value, LocationKey.PARENT.value, LocationKey.TYPE_ID.value} <= {
            index.document['name'] for index in indexes
        }

    def test_it_carries_no_version(self) -> None:
        """
        A location has no version of its own

        It mirrors an object rather than being edited, so the DEFAULT_VERSION this class used to
        declare was never read by anything - unlike CmdbObject's and CmdbType's.
        """
        assert 'DEFAULT_VERSION' not in vars(CmdbLocation)
        assert LocationKey.__members__.get('VERSION') is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the constructor                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """The validating place for the two keys a document may omit."""

    def test_the_values_are_stored_as_given(self) -> None:
        """Nothing is invented and nothing is dropped"""
        location = CmdbLocation(
            public_id=PUBLIC_ID, name=NAME, parent=PARENT_ID, object_id=OBJECT_ID,
            type_id=TYPE_ID, type_label=TYPE_LABEL, type_icon=TYPE_ICON, type_selectable=False,
        )

        assert location.get_public_id() == PUBLIC_ID
        assert location.name == NAME
        assert location.parent == PARENT_ID
        assert location.object_id == OBJECT_ID
        assert location.type_id == TYPE_ID
        assert location.type_label == TYPE_LABEL
        assert location.type_icon == TYPE_ICON
        assert location.type_selectable is False

    def test_the_optional_render_keys_default(self) -> None:
        """A node built without them renders with the generic icon and is a valid drop target"""
        location = CmdbLocation(
            public_id=PUBLIC_ID, name=NAME, parent=PARENT_ID, object_id=OBJECT_ID,
            type_id=TYPE_ID, type_label=TYPE_LABEL,
        )

        assert location.type_icon == CmdbLocationDefault.TYPE_ICON
        assert location.type_selectable is CmdbLocationDefault.TYPE_SELECTABLE

    @pytest.mark.parametrize('key', [LocationKey.TYPE_ICON.value, LocationKey.TYPE_SELECTABLE.value])
    def test_a_null_optional_key_reads_as_its_default(self, key: str) -> None:
        """A stored null used to reach the tree as null - the payload contradicted the default"""
        location = _location(**{key: None})

        assert getattr(location, key) == getattr(
            CmdbLocationDefault, 'TYPE_ICON' if key == LocationKey.TYPE_ICON.value else 'TYPE_SELECTABLE'
        )

    def test_a_non_boolean_selectable_is_refused(self) -> None:
        """The tree draws drop targets with 'type_selectable !== false', so a "false" would be one"""
        with pytest.raises(CmdbLocationInitError):
            CmdbLocation(
                public_id=PUBLIC_ID, name=NAME, parent=PARENT_ID, object_id=OBJECT_ID,
                type_id=TYPE_ID, type_label=TYPE_LABEL, type_selectable='false',
            )

    def test_a_non_text_icon_is_refused(self) -> None:
        """It reaches the frontend as a CSS class name"""
        with pytest.raises(CmdbLocationInitError):
            CmdbLocation(
                public_id=PUBLIC_ID, name=NAME, parent=PARENT_ID, object_id=OBJECT_ID,
                type_id=TYPE_ID, type_label=TYPE_LABEL, type_icon=7,
            )

    def test_an_unusable_render_key_surfaces_as_the_read_error_on_a_document(self) -> None:
        """
        Read through from_data, the constructor's refusal is reported as the read failing

        Which is what the route error tails map: a drifted document answers 400, not 500.
        """
        with pytest.raises(CmdbLocationInitFromDataError):
            _location(type_selectable='false')

    def test_the_constructor_is_keyword_only(self) -> None:
        """CmdbDAO.__new__ reads public_id out of **kwargs, so a positional call never worked"""
        with pytest.raises(RequiredInitKeyNotFoundError):
            # pylint: disable=too-many-function-args
            CmdbLocation(PUBLIC_ID, NAME, PARENT_ID, OBJECT_ID, TYPE_ID, TYPE_LABEL)  # type: ignore[misc]

    def test_a_direct_construction_missing_a_required_key_is_refused(self) -> None:
        """__new__ runs before __init__ and answers for the keyword that is not there"""
        with pytest.raises(RequiredInitKeyNotFoundError):
            # pylint: disable=missing-kwoa
            CmdbLocation(  # type: ignore[call-arg]
                public_id=PUBLIC_ID, parent=PARENT_ID, object_id=OBJECT_ID,
                type_id=TYPE_ID, type_label=TYPE_LABEL,
            )


# -------------------------------------------------------------------------------------------------------------------- #
#                                            from_data / to_json (shared)                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFromData:
    """Reading a stored document, through the shared implementation."""

    def test_a_document_round_trips(self) -> None:
        """The eight keys survive a read and a write unchanged"""
        assert CmdbLocation.to_json(_location()) == _document()

    def test_the_root_document_round_trips(self) -> None:
        """
        The synthetic root is a location like any other here

        It carries the 0 sentinels for parent, object_id and type_id - which is exactly the shape a
        required-key check must not mistake for a missing key.
        """
        root = CmdbLocation.from_data({
            LocationKey.PUBLIC_ID.value: RootLocationDefault.PUBLIC_ID,
            LocationKey.NAME.value: RootLocationDefault.NAME,
            LocationKey.PARENT.value: RootLocationDefault.NO_PARENT,
            LocationKey.OBJECT_ID.value: RootLocationDefault.NO_OBJECT,
            LocationKey.TYPE_ID.value: RootLocationDefault.NO_TYPE,
            LocationKey.TYPE_LABEL.value: RootLocationDefault.NAME,
            LocationKey.TYPE_ICON.value: RootLocationDefault.ICON,
            LocationKey.TYPE_SELECTABLE.value: RootLocationDefault.SELECTABLE,
        })

        assert root.get_public_id() == RootLocationDefault.PUBLIC_ID
        assert root.parent == RootLocationDefault.NO_PARENT
        assert root.object_id == RootLocationDefault.NO_OBJECT

    def test_the_mongo_id_is_not_carried_into_the_payload(self) -> None:
        """to_json emits exactly the enum's keys, which is what keeps '_id' out of a response"""
        assert '_id' not in CmdbLocation.to_json(_location(_id='507f1f77bcf86cd799439011'))

    @pytest.mark.parametrize('missing', [
        LocationKey.NAME.value,
        LocationKey.PARENT.value,
        LocationKey.OBJECT_ID.value,
        LocationKey.TYPE_ID.value,
        LocationKey.TYPE_LABEL.value,
    ])
    def test_a_document_missing_a_required_key_is_refused(self, missing: str) -> None:
        """
        It used to become an instance holding None

        REQUIRED_INIT_KEYS was declared but inert on this path: __new__ only checks that the keyword
        was passed, and from_data always passed all eight.
        """
        document = _document()
        del document[missing]

        with pytest.raises(CmdbLocationInitFromDataError):
            CmdbLocation.from_data(document)

    def test_the_error_names_the_missing_key(self) -> None:
        """The message is what an operator has to work from when a document is drifted"""
        document = _document()
        del document[LocationKey.TYPE_LABEL.value]

        with pytest.raises(CmdbLocationInitFromDataError) as err:
            CmdbLocation.from_data(document)

        assert LocationKey.TYPE_LABEL.value in str(err.value)

    @pytest.mark.parametrize('missing', [LocationKey.TYPE_ICON.value, LocationKey.TYPE_SELECTABLE.value])
    def test_a_document_missing_an_optional_key_is_accepted(self, missing: str) -> None:
        """The render metadata is a snapshot, and its absence is what the defaults are for"""
        document = _document()
        del document[missing]

        assert CmdbLocation.from_data(document) is not None

    def test_a_zero_public_id_is_refused_when_the_model_is_serialised(self) -> None:
        """
        CmdbDAO reads 0 as 'no public_id assigned', and no route could address such a node

        The refusal comes from ``get_public_id()`` inside the shared to_json rather than from the
        read: constructing is still possible, answering is not.
        """
        location = _location(public_id=0)

        with pytest.raises(CmdbLocationToJsonError):
            CmdbLocation.to_json(location)


class TestToJson:
    """Answering a document, through the shared implementation."""

    def test_the_key_order_is_the_enum_order(self) -> None:
        """The payload keys are a frontend contract, and the enum is where they are declared"""
        assert list(CmdbLocation.to_json(_location())) == [key.value for key in LocationKey]

    def test_a_foreign_instance_is_refused(self) -> None:
        """LocationNode carries five of these attribute names, so the guard is not theoretical"""
        class Impostor:
            """Carries the tree-node half of a location's attributes."""
            name = NAME
            parent = PARENT_ID
            object_id = OBJECT_ID
            type_icon = TYPE_ICON
            type_selectable = True

            def get_public_id(self) -> int:
                """The accessor to_json reads the id through"""
                return PUBLIC_ID

        with pytest.raises(CmdbLocationToJsonError):
            CmdbLocation.to_json(Impostor())  # type: ignore[arg-type]

    def test_a_dict_is_refused(self) -> None:
        """to_json takes an instance; handing it a raw document is a caller mistake"""
        with pytest.raises(CmdbLocationToJsonError):
            CmdbLocation.to_json(_document())  # type: ignore[arg-type]

    def test_it_is_a_cmdb_dao(self) -> None:
        """The public_id machinery every collection shares comes from there"""
        assert isinstance(_location(), CmdbDAO)

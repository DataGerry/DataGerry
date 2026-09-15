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
Integration tests for the two 'special_type' migrations against a real MongoDB

``updater_20260417`` gives every CmdbType and CmdbObject the key, writing the empty marker;
``updater_20260908`` then converges that marker and any still-missing key onto the ``None`` the model
and both Cerberus schemas use. They are tested together because the second only makes sense as the
successor of the first, and because the pair has to be **safe in any order and any number of runs** -
a customer database can be at either version when it is upgraded.

Both are asserted against real collections rather than stubs for one reason: their whole idempotence is
a query (``$exists`` / an ``$or`` over two states) with no database-level constraint behind it, so only
a real double run proves it. A stub can only confirm the query text.

What must never happen, and is asserted after every run: a document already carrying a real SpecialType
flavour is not touched. Neither migration may un-assign a RACK or a SUBNET.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20260417 import Update20260417
from cmdb.database.updater.versions.updater_20260908 import Update20260908
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

# A type/object pair in the pre-20260417 state: no 'special_type' key at all
LEGACY_TYPE_ID: int = 9840
LEGACY_OBJECT_ID: int = 9841

# A pair carrying the empty marker, i.e. the state 20260417 leaves behind
EMPTY_MARKER_TYPE_ID: int = 9842
EMPTY_MARKER_OBJECT_ID: int = 9843

# A pair carrying a real flavour, which neither migration may disturb
SPECIAL_TYPE_ID: int = 9844
SPECIAL_OBJECT_ID: int = 9845

ALL_TYPE_IDS: list[int] = [LEGACY_TYPE_ID, EMPTY_MARKER_TYPE_ID, SPECIAL_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [LEGACY_OBJECT_ID, EMPTY_MARKER_OBJECT_ID, SPECIAL_OBJECT_ID]

MISSING = object()


@pytest.fixture(name='special_type_documents', autouse=True)
def fixture_special_type_documents(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the three marker states in both collections, cleaning up before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})

    _purge()

    # no key at all - the pre-20260417 shape
    types.insert_one({'public_id': LEGACY_TYPE_ID, 'name': 'legacy-type'})
    objects.insert_one({'public_id': LEGACY_OBJECT_ID, 'type_id': LEGACY_TYPE_ID})
    # the empty marker - what 20260417 writes
    types.insert_one({'public_id': EMPTY_MARKER_TYPE_ID, 'name': 'empty-marker-type',
                      TypeSchemaKey.SPECIAL_TYPE.value: ''})
    objects.insert_one({'public_id': EMPTY_MARKER_OBJECT_ID, 'type_id': EMPTY_MARKER_TYPE_ID,
                        CmdbObjectKey.SPECIAL_TYPE.value: ''})
    # a real flavour - must survive both migrations untouched
    types.insert_one({'public_id': SPECIAL_TYPE_ID, 'name': 'rack-type',
                      TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value})
    objects.insert_one({'public_id': SPECIAL_OBJECT_ID, 'type_id': SPECIAL_TYPE_ID,
                        CmdbObjectKey.SPECIAL_TYPE.value: SpecialType.RACK.value})

    yield

    _purge()


def _marker(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, public_id: int, key: str) -> Any:
    """
    Reads one document's marker back, distinguishing a missing key from a null one

    Args:
        database_manager (MongoDatabaseManager): The manager to read through
        database_name (str): The database holding the collection
        collection (str): The collection to read
        public_id (int): The document to read
        key (str): The marker key

    Returns:
        Any: The stored marker, or the MISSING sentinel when the key is absent
    """
    document = database_manager.get_collection(collection, database_name).find_one(
        {'public_id': public_id}
    )

    return document.get(key, MISSING)


def _type_marker(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> Any:
    """Reads a seeded CmdbType's marker"""
    return _marker(database_manager, database_name, CmdbType.COLLECTION, public_id,
                   TypeSchemaKey.SPECIAL_TYPE.value)


def _object_marker(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> Any:
    """Reads a seeded CmdbObject's marker"""
    return _marker(database_manager, database_name, CmdbObject.COLLECTION, public_id,
                   CmdbObjectKey.SPECIAL_TYPE.value)


class TestUpdate20260417:
    """The backfill: every document gets the key, with the empty marker."""

    def test_the_missing_key_is_backfilled_in_both_collections(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The pre-migration pair has no key at all; after the run both carry the empty marker."""
        Update20260417(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, LEGACY_TYPE_ID) == ''
        assert _object_marker(database_manager, database_name, LEGACY_OBJECT_ID) == ''

    def test_a_real_flavour_is_left_alone(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The filter must never reach a type that already declares itself a RACK."""
        Update20260417(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, SPECIAL_TYPE_ID) == SpecialType.RACK.value
        assert _object_marker(database_manager, database_name, SPECIAL_OBJECT_ID) == SpecialType.RACK.value

    def test_a_second_run_changes_nothing(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """
        The double run, which is the point of testing this against a real collection

        Nothing at the database level would stop a second pass from rewriting documents; the
        ``$exists: False`` filter is the only thing that does, so it is proven rather than assumed.
        """
        Update20260417(database_manager, database_name).start_update()
        Update20260417(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, LEGACY_TYPE_ID) == ''
        assert _type_marker(database_manager, database_name, SPECIAL_TYPE_ID) == SpecialType.RACK.value
        assert _object_marker(database_manager, database_name, SPECIAL_OBJECT_ID) == SpecialType.RACK.value


class TestUpdate20260908:
    """The normalisation: the empty marker and the absent key both become null."""

    def test_the_empty_marker_becomes_null(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """What 20260417 wrote is converged onto the value the model produces."""
        Update20260908(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, EMPTY_MARKER_TYPE_ID) is None
        assert _object_marker(database_manager, database_name, EMPTY_MARKER_OBJECT_ID) is None

    def test_a_still_missing_key_also_becomes_null(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """
        A database that never ran 20260417 converges too

        This is what makes the pair order-independent: 20260908 alone leaves the same end state as
        20260417 followed by 20260908.
        """
        Update20260908(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, LEGACY_TYPE_ID) is None
        assert _object_marker(database_manager, database_name, LEGACY_OBJECT_ID) is None

    def test_a_real_flavour_is_left_alone(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The narrow $or must not be able to un-assign a RACK."""
        Update20260908(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, SPECIAL_TYPE_ID) == SpecialType.RACK.value
        assert _object_marker(database_manager, database_name, SPECIAL_OBJECT_ID) == SpecialType.RACK.value

    def test_a_second_run_changes_nothing(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A null marker no longer matches the filter, so the repeat is a no-op."""
        Update20260908(database_manager, database_name).start_update()
        Update20260908(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, EMPTY_MARKER_TYPE_ID) is None
        assert _type_marker(database_manager, database_name, LEGACY_TYPE_ID) is None
        assert _type_marker(database_manager, database_name, SPECIAL_TYPE_ID) == SpecialType.RACK.value


class TestThePairInSequence:
    """A customer database can be at either version when it is upgraded."""

    def test_the_chain_converges_on_one_spelling(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """
        After both migrations every document has the key, and it is a member or null

        That is the state the whole point of 20260908: no reader has to know that '' ever existed, and
        a future ``{'special_type': {'$ne': None}}`` means what it looks like it means.
        """
        Update20260417(database_manager, database_name).start_update()
        Update20260908(database_manager, database_name).start_update()

        markers = [
            _type_marker(database_manager, database_name, LEGACY_TYPE_ID),
            _type_marker(database_manager, database_name, EMPTY_MARKER_TYPE_ID),
            _object_marker(database_manager, database_name, LEGACY_OBJECT_ID),
            _object_marker(database_manager, database_name, EMPTY_MARKER_OBJECT_ID),
        ]

        assert markers == [None, None, None, None]
        assert MISSING not in markers
        assert _type_marker(database_manager, database_name, SPECIAL_TYPE_ID) == SpecialType.RACK.value

    def test_running_the_backfill_after_the_normalisation_is_harmless(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """
        The reverse order, which the runner cannot produce but a manual re-run can

        20260417's ``$exists: False`` filter no longer matches anything once 20260908 has written the
        key everywhere, so it cannot reintroduce the empty marker.
        """
        Update20260908(database_manager, database_name).start_update()
        Update20260417(database_manager, database_name).start_update()

        assert _type_marker(database_manager, database_name, LEGACY_TYPE_ID) is None
        assert _object_marker(database_manager, database_name, LEGACY_OBJECT_ID) is None

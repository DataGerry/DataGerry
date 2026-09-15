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
Integration tests for cmdb.database.updater.versions.updater_20260910 against a real MongoDB

Reproduces a pre-migration collection - object relations whose ``last_edit_time`` holds the
``{'$date': ...}`` wrapper the create route used to accept from the body - and asserts that the
conversion lands, that the result is a value MongoDB can actually sort and range-filter (the whole
point of the migration, and the one thing a stubbed manager cannot show), that a real value is left
alone, and that a second run changes nothing.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20260910 import Update20260910
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
# -------------------------------------------------------------------------------------------------------------------- #

STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)
LATER_MILLIS: int = 1700000000000
LATER: datetime = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

WRAPPED_ID: int = 9980
STRING_WRAPPED_ID: int = 9981
MIGRATED_ID: int = 9982
NEVER_EDITED_ID: int = 9983
UNREADABLE_ID: int = 9984
ALL_IDS: list[int] = [WRAPPED_ID, STRING_WRAPPED_ID, MIGRATED_ID, NEVER_EDITED_ID, UNREADABLE_ID]


def _relation_doc(public_id: int, **overrides: Any) -> dict[str, Any]:
    """Builds a minimal object-relation document for direct collection insertion"""
    document: dict[str, Any] = {
        ObjectRelationKey.PUBLIC_ID.value: public_id,
        ObjectRelationKey.RELATION_ID.value: 1,
        ObjectRelationKey.RELATION_PARENT_ID.value: 2,
        ObjectRelationKey.RELATION_PARENT_TYPE_ID.value: 3,
        ObjectRelationKey.RELATION_CHILD_ID.value: 4,
        ObjectRelationKey.RELATION_CHILD_TYPE_ID.value: 5,
        ObjectRelationKey.AUTHOR_ID.value: 1,
        ObjectRelationKey.CREATION_TIME.value: STAMP,
        ObjectRelationKey.FIELD_VALUES.value: [],
    }
    document.update(overrides)

    return document


@pytest.fixture(name='pre_migration_db', autouse=True)
def fixture_pre_migration_db(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds object relations in their pre-migration shapes, cleaning up after"""
    relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': ALL_IDS}})

    _purge()

    relations.insert_many([
        # What the create route stored when a client sent the frontend's wrapper
        _relation_doc(WRAPPED_ID, last_edit_time={'$date': LATER_MILLIS}),
        # The same wrapper carrying a timestamp string instead of millis
        _relation_doc(STRING_WRAPPED_ID, last_edit_time={'$date': '2023-11-14T22:13:20Z'}),
        # Already a real date: written after the fix, and the shape a re-run must not touch
        _relation_doc(MIGRATED_ID, last_edit_time=LATER),
        # Never edited, which is what a create writes now
        _relation_doc(NEVER_EDITED_ID, last_edit_time=None),
        # A sub-document that is not a wrapper: must survive rather than be nulled
        _relation_doc(UNREADABLE_ID, last_edit_time={'legacy_shape': True}),
    ])

    yield

    _purge()


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260910(database_manager, database_name).start_update()


def _relation(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads one seeded object relation back"""
    return database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                           .find_one({ObjectRelationKey.PUBLIC_ID.value: public_id})


class TestConversion:
    """What the migration rewrites."""

    def test_a_wrapped_millis_value_becomes_a_real_date(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The shape the frontend sends, which passed validation and was stored verbatim."""
        _run_migration(database_manager, database_name)

        assert _relation(database_manager, database_name, WRAPPED_ID)[
            ObjectRelationKey.LAST_EDIT_TIME.value
        ] == LATER.replace(tzinfo=None)

    def test_a_wrapped_string_value_becomes_a_real_date(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """$convert reads the timestamp string inside the wrapper as well as the millis."""
        _run_migration(database_manager, database_name)

        assert _relation(database_manager, database_name, STRING_WRAPPED_ID)[
            ObjectRelationKey.LAST_EDIT_TIME.value
        ] == LATER.replace(tzinfo=None)

    def test_the_creation_time_is_left_as_the_date_it_already_was(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Selection is by BSON type, so a key already holding a date is never rewritten."""
        _run_migration(database_manager, database_name)

        assert _relation(database_manager, database_name, WRAPPED_ID)[
            ObjectRelationKey.CREATION_TIME.value
        ] == STAMP.replace(tzinfo=None)


class TestWhatMustSurvive:
    """The values the migration must not destroy."""

    def test_a_never_edited_relation_keeps_its_null(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """'Never edited' is a real state; turning it into a date would invent an edit."""
        _run_migration(database_manager, database_name)

        assert _relation(database_manager, database_name, NEVER_EDITED_ID)[
            ObjectRelationKey.LAST_EDIT_TIME.value
        ] is None

    def test_an_unreadable_sub_document_is_left_alone(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The two fallback arms of the pipeline

        Nulling a value nobody can read would destroy the only evidence of what was stored, so the
        conversion leaves it and an operator can look at it.
        """
        _run_migration(database_manager, database_name)

        assert _relation(database_manager, database_name, UNREADABLE_ID)[
            ObjectRelationKey.LAST_EDIT_TIME.value
        ] == {'legacy_shape': True}


class TestTheResultIsSortable:
    """The reason the migration exists."""

    def test_the_converted_values_sort_and_range_filter_as_dates(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        A sub-document cannot be compared as a date, and the relation-tab route accepts ?sort=

        Asserted against a real server because this is exactly what a stubbed manager cannot show: the
        query returns the two converted relations and orders them, where before it returned neither.
        """
        _run_migration(database_manager, database_name)

        relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
        matched = list(relations.find(
            {
                ObjectRelationKey.PUBLIC_ID.value: {'$in': ALL_IDS},
                ObjectRelationKey.LAST_EDIT_TIME.value: {'$gte': STAMP.replace(tzinfo=None)},
            },
            {ObjectRelationKey.PUBLIC_ID.value: 1},
        ).sort(ObjectRelationKey.LAST_EDIT_TIME.value, 1))

        assert {row[ObjectRelationKey.PUBLIC_ID.value] for row in matched} == {
            WRAPPED_ID, STRING_WRAPPED_ID, MIGRATED_ID,
        }


class TestReRun:
    """The property every migration in this package has to have."""

    def test_a_second_run_changes_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The whole registry re-runs on a database whose version is behind, so this is not theoretical."""
        _run_migration(database_manager, database_name)

        after_first = [_relation(database_manager, database_name, public_id) for public_id in ALL_IDS]

        _run_migration(database_manager, database_name)

        after_second = [_relation(database_manager, database_name, public_id) for public_id in ALL_IDS]

        assert after_first == after_second

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
Integration tests for cmdb.database.updater.versions.updater_20260909 against a real MongoDB

Reproduces a pre-migration database - persons and person groups whose optional keys hold null or are
missing entirely - and asserts that the migration converges them, that a real value is never touched,
and that a second run changes nothing.

A real server is needed for the part that matters: whether MongoDB's ``$exists`` / null filter really
does pass over a document that already holds an empty value is the whole re-run-safety argument, and a
stubbed manager can only prove the filter's shape. The end state is then checked the way the API sees
it - the stored documents pass their own Cerberus schema, which is the round trip that used to be
answered 400
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20260909 import Update20260909
from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey
# -------------------------------------------------------------------------------------------------------------------- #

NULLED_PERSON_ID: int = 9960
KEYLESS_PERSON_ID: int = 9961
POPULATED_PERSON_ID: int = 9962
ALL_PERSON_IDS: list[int] = [NULLED_PERSON_ID, KEYLESS_PERSON_ID, POPULATED_PERSON_ID]

NULLED_GROUP_ID: int = 9970
KEYLESS_GROUP_ID: int = 9971
POPULATED_GROUP_ID: int = 9972
ALL_GROUP_IDS: list[int] = [NULLED_GROUP_ID, KEYLESS_GROUP_ID, POPULATED_GROUP_ID]

PHONE: str = '+491234567'
EMAIL: str = 'ada@example.com'
GROUP_EMAIL: str = 'security@example.com'


@pytest.fixture(name='pre_migration_db', autouse=True)
def fixture_pre_migration_db(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds persons and groups in their pre-migration shapes, cleaning up after"""
    persons = database_manager.get_collection(CmdbPerson.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)

    def _purge() -> None:
        persons.delete_many({'public_id': {'$in': ALL_PERSON_IDS}})
        groups.delete_many({'public_id': {'$in': ALL_GROUP_IDS}})

    _purge()

    persons.insert_many([
        {
            # What the model used to write for a payload without the optional keys
            'public_id': NULLED_PERSON_ID,
            PersonKey.DISPLAY_NAME.value: 'Ada Lovelace',
            PersonKey.FIRST_NAME.value: 'Ada',
            PersonKey.LAST_NAME.value: 'Lovelace',
            PersonKey.PHONE_NUMBER.value: None,
            PersonKey.EMAIL.value: None,
            PersonKey.GROUPS.value: None,
        },
        {
            # What a create wrote: the optional keys are simply not there
            'public_id': KEYLESS_PERSON_ID,
            PersonKey.DISPLAY_NAME.value: 'Grace Hopper',
            PersonKey.FIRST_NAME.value: 'Grace',
            PersonKey.LAST_NAME.value: 'Hopper',
        },
        {
            'public_id': POPULATED_PERSON_ID,
            PersonKey.DISPLAY_NAME.value: 'Alan Turing',
            PersonKey.FIRST_NAME.value: 'Alan',
            PersonKey.LAST_NAME.value: 'Turing',
            PersonKey.PHONE_NUMBER.value: PHONE,
            PersonKey.EMAIL.value: EMAIL,
            PersonKey.GROUPS.value: [NULLED_GROUP_ID],
        },
    ])
    groups.insert_many([
        {
            'public_id': NULLED_GROUP_ID,
            PersonGroupKey.NAME.value: 'Nulled',
            PersonGroupKey.EMAIL.value: None,
            PersonGroupKey.GROUP_MEMBERS.value: None,
        },
        {
            'public_id': KEYLESS_GROUP_ID,
            PersonGroupKey.NAME.value: 'Keyless',
        },
        {
            'public_id': POPULATED_GROUP_ID,
            PersonGroupKey.NAME.value: 'Populated',
            PersonGroupKey.EMAIL.value: GROUP_EMAIL,
            PersonGroupKey.GROUP_MEMBERS.value: [POPULATED_PERSON_ID],
        },
    ])

    yield

    _purge()


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260909(database_manager, database_name).start_update()


def _person(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads one seeded person back"""
    return database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
                           .find_one({'public_id': public_id})


def _group(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads one seeded person group back"""
    return database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
                           .find_one({'public_id': public_id})


class TestNullsAreConverged:
    """The documents the models used to write."""

    def test_a_nulled_person_gets_the_empty_values(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The three optional keys of a person, all null before the run."""
        _run_migration(database_manager, database_name)

        person = _person(database_manager, database_name, NULLED_PERSON_ID)

        assert person[PersonKey.PHONE_NUMBER.value] == ''
        assert person[PersonKey.EMAIL.value] == ''
        assert person[PersonKey.GROUPS.value] == []

    def test_a_nulled_group_gets_the_empty_values(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The membership null is the one that produced a 500

        The update route read it as set(None); after the migration there is nothing left to read
        that way.
        """
        _run_migration(database_manager, database_name)

        group = _group(database_manager, database_name, NULLED_GROUP_ID)

        assert group[PersonGroupKey.EMAIL.value] == ''
        assert group[PersonGroupKey.GROUP_MEMBERS.value] == []

    def test_the_missing_keys_are_filled_in(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        A document that never carried the key is the other half of the same problem

        The Angular person form turns an absent email into a null in its payload, so a person created
        through the API and then edited in the UI hit the 400 without a null ever being stored.
        """
        _run_migration(database_manager, database_name)

        person = _person(database_manager, database_name, KEYLESS_PERSON_ID)
        group = _group(database_manager, database_name, KEYLESS_GROUP_ID)

        assert person[PersonKey.EMAIL.value] == ''
        assert person[PersonKey.GROUPS.value] == []
        assert group[PersonGroupKey.GROUP_MEMBERS.value] == []


class TestRealValuesSurvive:
    """What the migration must never touch."""

    def test_a_populated_person_is_left_alone(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The filter matches null and absent only, so a real value cannot be overwritten."""
        _run_migration(database_manager, database_name)

        person = _person(database_manager, database_name, POPULATED_PERSON_ID)

        assert person[PersonKey.PHONE_NUMBER.value] == PHONE
        assert person[PersonKey.EMAIL.value] == EMAIL
        assert person[PersonKey.GROUPS.value] == [NULLED_GROUP_ID]

    def test_a_populated_group_is_left_alone(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Including its membership, which an over-broad filter would empty."""
        _run_migration(database_manager, database_name)

        group = _group(database_manager, database_name, POPULATED_GROUP_ID)

        assert group[PersonGroupKey.EMAIL.value] == GROUP_EMAIL
        assert group[PersonGroupKey.GROUP_MEMBERS.value] == [POPULATED_PERSON_ID]


class TestTheResultIsWhatTheApiExpects:
    """The end state, checked the way a client sees it."""

    @pytest.mark.parametrize('public_id', ALL_PERSON_IDS)
    def test_every_person_document_passes_the_person_schema(
        self, database_manager: MongoDatabaseManager, database_name: str, public_id: int,
    ) -> None:
        """
        GET then an unmodified PUT, which is what every DataGerry write route expects

        This is the assertion the whole migration exists for: before it, two of these three documents
        were refused by the very schema that produced them.
        """
        _run_migration(database_manager, database_name)

        document: dict[str, Any] = _person(database_manager, database_name, public_id)
        document.pop('_id')
        validator = Validator(CmdbPerson.SCHEMA)

        assert validator.validate(document), validator.errors

    @pytest.mark.parametrize('public_id', ALL_GROUP_IDS)
    def test_every_group_document_passes_the_group_schema(
        self, database_manager: MongoDatabaseManager, database_name: str, public_id: int,
    ) -> None:
        """The same round trip on the group side."""
        _run_migration(database_manager, database_name)

        document: dict[str, Any] = _group(database_manager, database_name, public_id)
        document.pop('_id')
        validator = Validator(CmdbPersonGroup.SCHEMA)

        assert validator.validate(document), validator.errors


class TestReRun:
    """The property every migration in this package has to have."""

    def test_a_second_run_changes_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The whole registry re-runs on a database whose version is behind, so this is not theoretical

        Asserted over the documents rather than over a modified_count, because what matters is that
        the data is identical - a re-run that rewrote the same values would also be a re-run that
        could rewrite the wrong ones.
        """
        _run_migration(database_manager, database_name)

        after_first: list[dict[str, Any]] = [
            _person(database_manager, database_name, public_id) for public_id in ALL_PERSON_IDS
        ] + [
            _group(database_manager, database_name, public_id) for public_id in ALL_GROUP_IDS
        ]

        _run_migration(database_manager, database_name)

        after_second: list[dict[str, Any]] = [
            _person(database_manager, database_name, public_id) for public_id in ALL_PERSON_IDS
        ] + [
            _group(database_manager, database_name, public_id) for public_id in ALL_GROUP_IDS
        ]

        assert after_first == after_second

    def test_the_second_run_matches_no_document(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The filter, checked against a real server rather than by its shape

        MongoDB deciding that '' is neither null nor absent is what makes the re-run free; a filter
        of {'$in': [None, '']} would look just as reasonable and would rewrite everything, every
        start.
        """
        _run_migration(database_manager, database_name)

        persons = database_manager.get_collection(CmdbPerson.COLLECTION, database_name)
        still_matching: int = persons.count_documents({
            'public_id': {'$in': ALL_PERSON_IDS},
            '$or': [
                {PersonKey.EMAIL.value: None},
                {PersonKey.EMAIL.value: {'$exists': False}},
            ],
        })

        assert still_matching == 0

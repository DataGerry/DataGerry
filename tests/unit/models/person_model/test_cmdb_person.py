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
Unit tests for cmdb.models.person_model

Pure tests: no Mongo, no Flask. The rules CmdbPerson shares with the other two membership models -
that a stored document holds no null, that to_json is exactly the key enum, that a required key is
refused - are pinned once in tests/unit/models/test_membership_models_are_null_free.py. What is pinned
here is what belongs to the person alone:

  - the ``groups`` index, which the group-deletion cascade needs and which this model did not declare:
    ``delete_group_from_persons`` filters on ``{'groups': group_id}``, and its twin index on the other
    side of the pair (``group_members``) had existed all along
  - the collection reaching CollectionValidator through the user-management registry, without which no
    index of it is ever built
  - the constructor's coercions and its error wrapping
  - what the schema accepts, in particular the email pattern and the nullable optional keys
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.person_model import CmdbPerson, PersonKey, PERSON_LIST_KEYS, PERSON_OPTIONAL_TEXT_KEYS
from cmdb.models.user_management_constants import __COLLECTIONS__ as USER_MANAGEMENT_COLLECTIONS
from cmdb.class_schema.person_model.cmdb_person_schema import get_cmdb_person_schema
from cmdb.errors.models.cmdb_person import CmdbPersonInitError, CmdbPersonToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 12


def _person(**overrides: Any) -> CmdbPerson:
    """Builds a CmdbPerson from a complete payload, with the given keys replaced"""
    payload: dict[str, Any] = {
        PersonKey.PUBLIC_ID.value: PUBLIC_ID,
        PersonKey.DISPLAY_NAME.value: 'Ada Lovelace',
        PersonKey.FIRST_NAME.value: 'Ada',
        PersonKey.LAST_NAME.value: 'Lovelace',
        PersonKey.PHONE_NUMBER.value: '+491234567',
        PersonKey.EMAIL.value: 'ada@example.com',
        PersonKey.GROUPS.value: [2, 3],
    }
    payload.update(overrides)

    return CmdbPerson.from_data(payload)


class TestCollectionAndIndexes:
    """What the collection is, and which lookups are answered by an index."""

    def test_stores_in_the_management_person_collection(self) -> None:
        """The collection name is part of every cascade that writes it from another manager."""
        assert CmdbPerson.COLLECTION == 'management.person'

    def test_reaches_the_collection_validator_through_the_user_management_registry(self) -> None:
        """
        A model in no registry has no collection created and therefore no index built

        CmdbPerson is registered in the user-management list rather than the framework one, which is
        why it does not appear in cmdb.framework.constants.
        """
        assert CmdbPerson in USER_MANAGEMENT_COLLECTIONS

    def test_indexes_the_groups_membership_key(self) -> None:
        """
        The group cascade filters on 'groups', and without this index that is a collection scan

        Deleting or editing a CmdbPersonGroup pulls it out of every person listing it, so the query
        runs on an ordinary write path rather than only in a migration.
        """
        index_names: set[str] = {index.document['name'] for index in CmdbPerson.get_index_keys()}

        assert PersonKey.GROUPS.value in index_names

    def test_keeps_the_inherited_unique_public_id_index(self) -> None:
        """The identity index every CmdbDAO gets; declaring INDEX_KEYS must not displace it."""
        public_id_indexes = [
            index for index in CmdbPerson.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        ]

        assert len(public_id_indexes) == 1
        assert public_id_indexes[0].document['unique'] is True


class TestConstructor:
    """The coercions, and the error the constructor raises."""

    def test_keeps_the_values_it_is_given(self) -> None:
        """A complete payload is stored verbatim - the coercions only ever fill in an absent value."""
        stored: dict[str, Any] = CmdbPerson.to_json(_person())

        assert stored[PersonKey.PHONE_NUMBER.value] == '+491234567'
        assert stored[PersonKey.EMAIL.value] == 'ada@example.com'
        assert stored[PersonKey.GROUPS.value] == [2, 3]

    @pytest.mark.parametrize('key', PERSON_OPTIONAL_TEXT_KEYS)
    def test_an_empty_optional_text_key_stays_empty(self, key: str) -> None:
        """'' is the house marker for 'no value' here, and it must survive a round trip unchanged."""
        assert CmdbPerson.to_json(_person(**{key: ''}))[key] == ''

    @pytest.mark.parametrize('key', PERSON_LIST_KEYS)
    def test_an_empty_list_key_stays_empty(self, key: str) -> None:
        """A person who is in no group is not the same as one whose groups were never written."""
        assert CmdbPerson.to_json(_person(**{key: []}))[key] == []

    def test_every_person_gets_a_fresh_groups_list(self) -> None:
        """
        The coerced default must not be shared between instances

        A mutable default on the signature would make two persons created without groups share one
        list, so editing one membership would edit the other's.
        """
        first, second = _person(groups=None), _person(groups=None)
        first.groups.append(99)

        assert second.groups == []

    def test_a_bad_public_id_surfaces_as_the_models_own_error(self) -> None:
        """The constructor's except arm: CmdbDAO casts public_id to int, and 'x' cannot be cast."""
        with pytest.raises(CmdbPersonInitError):
            CmdbPerson(
                public_id='x',
                display_name='Ada',
                first_name='Ada',
                last_name='Lovelace',
            )

    def test_to_json_of_a_person_missing_its_public_id_is_the_models_own_error(self) -> None:
        """get_public_id refuses an unassigned id, and the shared to_json wraps that as ToJsonError."""
        person: CmdbPerson = _person()
        del person.public_id

        with pytest.raises(CmdbPersonToJsonError):
            CmdbPerson.to_json(person)


class TestSchema:
    """What a payload may say, which is now a superset of what is stored."""

    def test_the_schema_is_built_from_the_key_enum(self) -> None:
        """A key renamed in the enum cannot leave the schema validating the old spelling."""
        assert set(get_cmdb_person_schema()) == {key.value for key in PersonKey}

    @pytest.mark.parametrize('key', PERSON_OPTIONAL_TEXT_KEYS + PERSON_LIST_KEYS)
    def test_the_optional_keys_accept_null(self, key: str) -> None:
        """
        A client with no value for a key may say so with null

        The Angular person form sends email as null for a person that has none; before this the API
        answered 400 'Invalid data provided!' and named nothing.
        """
        assert get_cmdb_person_schema()[key].get('nullable') is True

    def test_a_malformed_email_is_refused(self) -> None:
        """The pattern is the only validation the email gets, and it still applies."""
        validator = Validator(get_cmdb_person_schema())

        assert not validator.validate({
            PersonKey.DISPLAY_NAME.value: 'Ada',
            PersonKey.FIRST_NAME.value: 'Ada',
            PersonKey.LAST_NAME.value: 'Lovelace',
            PersonKey.EMAIL.value: 'not-an-email',
        })

    def test_the_required_names_are_refused_when_empty(self) -> None:
        """A person with a blank display name is unusable in every ISMS view that lists people."""
        validator = Validator(get_cmdb_person_schema())

        assert not validator.validate({
            PersonKey.DISPLAY_NAME.value: '',
            PersonKey.FIRST_NAME.value: 'Ada',
            PersonKey.LAST_NAME.value: 'Lovelace',
        })

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
Unit tests for cmdb.models.person_group_model

Pure tests: no Mongo, no Flask. The rules shared with the other two membership models are pinned once
in tests/unit/models/test_membership_models_are_null_free.py; what is pinned here belongs to the group
alone:

  - the ``group_members`` index and the registry membership that gets it built
  - the ``group_members: null`` document that used to be reachable, which is the value that made the
    update route read ``set(None)`` and answer 500 - the model can no longer produce it
  - ``email`` being required-but-empty here while it is optional on a person: the one place the two
    schemas differ, and easy to "harmonise" by accident
  - PersonReferenceType, the enum every polymorphic ISMS reference is stored beside
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.person_group_model import (
    CmdbPersonGroup,
    PersonGroupKey,
    PersonReferenceType,
    PERSON_GROUP_LIST_KEYS,
    PERSON_GROUP_OPTIONAL_TEXT_KEYS,
)
from cmdb.models.user_management_constants import __COLLECTIONS__ as USER_MANAGEMENT_COLLECTIONS
from cmdb.class_schema.person_group_model.cmdb_person_group_schema import get_cmdb_person_group_schema
from cmdb.class_schema.person_model.cmdb_person_schema import get_cmdb_person_schema
from cmdb.errors.models.cmdb_person_group import CmdbPersonGroupInitError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 5


def _group(**overrides: Any) -> CmdbPersonGroup:
    """Builds a CmdbPersonGroup from a complete payload, with the given keys replaced"""
    payload: dict[str, Any] = {
        PersonGroupKey.PUBLIC_ID.value: PUBLIC_ID,
        PersonGroupKey.NAME.value: 'Security officers',
        PersonGroupKey.GROUP_MEMBERS.value: [7, 8],
        PersonGroupKey.EMAIL.value: 'security@example.com',
    }
    payload.update(overrides)

    return CmdbPersonGroup.from_data(payload)


class TestCollectionAndIndexes:
    """What the collection is, and which lookups are answered by an index."""

    def test_stores_in_the_management_person_group_collection(self) -> None:
        """The collection name is part of every cascade that writes it from another manager."""
        assert CmdbPersonGroup.COLLECTION == 'management.personGroup'

    def test_reaches_the_collection_validator_through_the_user_management_registry(self) -> None:
        """A model in no registry has no collection created and therefore no index built."""
        assert CmdbPersonGroup in USER_MANAGEMENT_COLLECTIONS

    def test_indexes_the_group_members_membership_key(self) -> None:
        """The person cascade filters on 'group_members' on an ordinary write path."""
        index_names: set[str] = {index.document['name'] for index in CmdbPersonGroup.get_index_keys()}

        assert PersonGroupKey.GROUP_MEMBERS.value in index_names

    def test_keeps_the_inherited_unique_public_id_index(self) -> None:
        """The identity index every CmdbDAO gets; declaring INDEX_KEYS must not displace it."""
        public_id_indexes = [
            index for index in CmdbPersonGroup.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        ]

        assert len(public_id_indexes) == 1
        assert public_id_indexes[0].document['unique'] is True


class TestTheNullMembershipCannotComeBack:
    """The exact value behind the 500, pinned from the model's side."""

    def test_a_payload_without_group_members_stores_an_empty_list(self) -> None:
        """
        This is how the null got in: the key was simply absent from the payload

        The route validates a body that omits group_members (the key is not required), the model used
        to turn that into null, and the NEXT update of the same group read set(None) and raised
        inside the route's try block - reported as a 500 saying nothing.
        """
        payload: dict[str, Any] = {
            PersonGroupKey.PUBLIC_ID.value: PUBLIC_ID,
            PersonGroupKey.NAME.value: 'Security officers',
        }

        assert CmdbPersonGroup.to_json(CmdbPersonGroup.from_data(payload))[
            PersonGroupKey.GROUP_MEMBERS.value
        ] == []

    def test_a_legacy_null_membership_is_read_as_an_empty_list(self) -> None:
        """
        Reading a document written before the fix must not reproduce the null

        updater_20260909 converges the stored documents, but a read has to be safe on its own: the
        migration and the model are two independent guarantees, not one.
        """
        legacy: dict[str, Any] = {
            PersonGroupKey.PUBLIC_ID.value: PUBLIC_ID,
            PersonGroupKey.NAME.value: 'Security officers',
            PersonGroupKey.GROUP_MEMBERS.value: None,
            PersonGroupKey.EMAIL.value: None,
        }

        stored: dict[str, Any] = CmdbPersonGroup.to_json(CmdbPersonGroup.from_data(legacy))

        assert stored[PersonGroupKey.GROUP_MEMBERS.value] == []
        assert stored[PersonGroupKey.EMAIL.value] == ''

    def test_every_group_gets_a_fresh_member_list(self) -> None:
        """The coerced default must not be shared between instances."""
        first, second = _group(group_members=None), _group(group_members=None)
        first.group_members.append(99)

        assert second.group_members == []


class TestConstructor:
    """The values it keeps, and the error it raises."""

    def test_keeps_the_values_it_is_given(self) -> None:
        """A complete payload is stored verbatim."""
        stored: dict[str, Any] = CmdbPersonGroup.to_json(_group())

        assert stored[PersonGroupKey.GROUP_MEMBERS.value] == [7, 8]
        assert stored[PersonGroupKey.EMAIL.value] == 'security@example.com'

    def test_a_bad_public_id_surfaces_as_the_models_own_error(self) -> None:
        """The constructor's except arm: CmdbDAO casts public_id to int, and 'x' cannot be cast."""
        with pytest.raises(CmdbPersonGroupInitError):
            CmdbPersonGroup(public_id='x', name='Security officers')


class TestSchema:
    """What a payload may say, including the one deliberate difference from the person schema."""

    def test_the_schema_is_built_from_the_key_enum(self) -> None:
        """A key renamed in the enum cannot leave the schema validating the old spelling."""
        assert set(get_cmdb_person_group_schema()) == {key.value for key in PersonGroupKey}

    @pytest.mark.parametrize('key', PERSON_GROUP_OPTIONAL_TEXT_KEYS + PERSON_GROUP_LIST_KEYS)
    def test_the_optional_keys_accept_null(self, key: str) -> None:
        """A client with no value for a key may say so with null."""
        assert get_cmdb_person_group_schema()[key].get('nullable') is True

    def test_email_is_required_here_and_optional_on_a_person(self) -> None:
        """
        The one place the twin schemas differ, asserted so that 'harmonising' them is a decision

        A group is a contact address as much as a set of people, so the key is always carried - blank
        if there is none. A person may simply not have the key at all.
        """
        group_email = get_cmdb_person_group_schema()[PersonGroupKey.EMAIL.value]
        person_email = get_cmdb_person_schema()['email']

        assert group_email['required'] is True
        assert group_email['empty'] is True
        assert person_email['required'] is False

    def test_a_malformed_email_is_refused(self) -> None:
        """The pattern is the only validation the email gets, and it still applies."""
        validator = Validator(get_cmdb_person_group_schema())

        assert not validator.validate({
            PersonGroupKey.NAME.value: 'Security officers',
            PersonGroupKey.EMAIL.value: 'not-an-email',
        })


class TestPersonReferenceType:
    """The enum that says which kind a polymorphic ISMS reference holds."""

    def test_holds_exactly_the_two_referenceable_kinds(self) -> None:
        """
        Every polymorphic ISMS field is stored beside a '_ref_type' carrying one of these

        A third member would need a cascade of its own in both person managers, so the pair is
        pinned here rather than assumed there.
        """
        assert {member.value for member in PersonReferenceType} == {'PERSON', 'PERSON_GROUP'}

    def test_members_compare_equal_to_their_stored_string(self) -> None:
        """The cascades filter with the member's value, and read documents written as plain strings."""
        assert PersonReferenceType.PERSON == 'PERSON'
        assert PersonReferenceType.PERSON_GROUP.value == 'PERSON_GROUP'

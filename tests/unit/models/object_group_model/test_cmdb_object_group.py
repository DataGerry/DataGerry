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
Unit tests for cmdb.models.object_group_model

Pure tests: no Mongo, no Flask. The rules shared with the two person models are pinned once in
tests/unit/models/test_membership_models_are_null_free.py; what is pinned here belongs to the object
group alone:

  - **``group_type`` is constrained to ObjectGroupMode.** It used to be any string, and a group stored
    with a third value is invisible to BOTH cleanup paths (objects_helper maintains the STATIC groups,
    types_helper the DYNAMIC ones), so it keeps deleted ids forever. The schema rule is the only thing
    standing between a typo and that state
  - the two indexes the cleanup paths need, and the framework registry that gets them built
  - ``assigned_ids`` being required and non-empty, which is what makes a group always mean something
  - the option type that ties ``categories`` to the CmdbExtendableOption list, not to CmdbCategories
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_COLLECTIONS
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.object_group_model import (
    CmdbObjectGroup,
    ObjectGroupKey,
    ObjectGroupMode,
    ObjectReferenceType,
)
from cmdb.class_schema.object_group_model.cmdb_object_group_schema import get_cmdb_object_group_schema
from cmdb.errors.models.cmdb_object_group import CmdbObjectGroupInitError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 9


def _payload(**overrides: Any) -> dict[str, Any]:
    """Builds a complete CmdbObjectGroup payload, with the given keys replaced"""
    payload: dict[str, Any] = {
        ObjectGroupKey.PUBLIC_ID.value: PUBLIC_ID,
        ObjectGroupKey.NAME.value: 'Core switches',
        ObjectGroupKey.GROUP_TYPE.value: ObjectGroupMode.STATIC.value,
        ObjectGroupKey.ASSIGNED_IDS.value: [1, 2],
        ObjectGroupKey.CATEGORIES.value: [4],
    }
    payload.update(overrides)

    return payload


class TestGroupTypeIsConstrained:
    """The rule that keeps a group reachable by the cleanup that maintains it."""

    @pytest.mark.parametrize('mode', list(ObjectGroupMode), ids=lambda mode: mode.value)
    def test_every_mode_is_accepted(self, mode: ObjectGroupMode) -> None:
        """Adding a mode to the enum must not need a second edit in the schema."""
        validator = Validator(get_cmdb_object_group_schema())

        assert validator.validate(_payload(group_type=mode.value)), validator.errors

    def test_a_third_value_is_refused(self) -> None:
        """
        A group whose mode is neither STATIC nor DYNAMIC is maintained by nobody

        Deleting an object pulls its id out of the STATIC groups, deleting a type out of the DYNAMIC
        ones; a group outside both keeps ids pointing at documents that no longer exist, and nothing
        ever visits it again.
        """
        validator = Validator(get_cmdb_object_group_schema())

        assert not validator.validate(_payload(group_type='SOMETHING_ELSE'))
        assert 'group_type' in validator.errors

    def test_the_allowed_values_are_taken_from_the_enum(self) -> None:
        """Read from ObjectGroupMode rather than spelled out, so the two cannot drift."""
        allowed = get_cmdb_object_group_schema()[ObjectGroupKey.GROUP_TYPE.value]['allowed']

        assert set(allowed) == {mode.value for mode in ObjectGroupMode}


class TestCollectionAndIndexes:
    """What the collection is, and which lookups are answered by an index."""

    def test_stores_in_the_framework_object_groups_collection(self) -> None:
        """The collection name is part of the ISMS cascade that reads it."""
        assert CmdbObjectGroup.COLLECTION == 'framework.objectGroups'

    def test_reaches_the_collection_validator_through_the_framework_registry(self) -> None:
        """A model in no registry has no collection created and therefore no index built."""
        assert CmdbObjectGroup in FRAMEWORK_COLLECTIONS

    def test_indexes_the_two_keys_the_cleanup_paths_filter_on(self) -> None:
        """Both cleanups select by mode and by member id, on an ordinary object/type delete."""
        index_names: set[str] = {index.document['name'] for index in CmdbObjectGroup.get_index_keys()}

        assert {ObjectGroupKey.GROUP_TYPE.value, ObjectGroupKey.ASSIGNED_IDS.value} <= index_names

    def test_keeps_the_inherited_unique_public_id_index(self) -> None:
        """The identity index every CmdbDAO gets; declaring INDEX_KEYS must not displace it."""
        public_id_indexes = [
            index for index in CmdbObjectGroup.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        ]

        assert len(public_id_indexes) == 1
        assert public_id_indexes[0].document['unique'] is True


class TestConstructor:
    """The values it keeps, and the error it raises."""

    def test_keeps_the_values_it_is_given(self) -> None:
        """A complete payload is stored verbatim."""
        stored: dict[str, Any] = CmdbObjectGroup.to_json(CmdbObjectGroup.from_data(_payload()))

        assert stored[ObjectGroupKey.GROUP_TYPE.value] == ObjectGroupMode.STATIC.value
        assert stored[ObjectGroupKey.ASSIGNED_IDS.value] == [1, 2]
        assert stored[ObjectGroupKey.CATEGORIES.value] == [4]

    def test_a_missing_categories_list_becomes_empty(self) -> None:
        """A group filed under nothing is a normal group, not a group with a null."""
        payload: dict[str, Any] = _payload()
        payload.pop(ObjectGroupKey.CATEGORIES.value)

        stored: dict[str, Any] = CmdbObjectGroup.to_json(CmdbObjectGroup.from_data(payload))

        assert stored[ObjectGroupKey.CATEGORIES.value] == []

    def test_every_group_gets_a_fresh_categories_list(self) -> None:
        """The coerced default must not be shared between instances."""
        first = CmdbObjectGroup.from_data(_payload(categories=None))
        second = CmdbObjectGroup.from_data(_payload(categories=None))
        first.categories.append(99)

        assert second.categories == []

    def test_a_bad_public_id_surfaces_as_the_models_own_error(self) -> None:
        """The constructor's except arm: CmdbDAO casts public_id to int, and 'x' cannot be cast."""
        with pytest.raises(CmdbObjectGroupInitError):
            CmdbObjectGroup(
                public_id='x',
                name='Core switches',
                group_type=ObjectGroupMode.STATIC,
                assigned_ids=[1],
            )


class TestSchema:
    """What a payload may say."""

    def test_the_schema_is_built_from_the_key_enum(self) -> None:
        """A key renamed in the enum cannot leave the schema validating the old spelling."""
        assert set(get_cmdb_object_group_schema()) == {key.value for key in ObjectGroupKey}

    def test_an_empty_assigned_ids_list_is_refused(self) -> None:
        """
        A group of nothing has no meaning, so emptying one is a deletion rather than an update

        Pinned because it is the only list key here that is NOT nullable, and the asymmetry is
        deliberate.
        """
        validator = Validator(get_cmdb_object_group_schema())

        assert not validator.validate(_payload(assigned_ids=[]))

    def test_categories_accept_null(self) -> None:
        """The one nullable key: a group filed under nothing may say so."""
        assert get_cmdb_object_group_schema()[ObjectGroupKey.CATEGORIES.value].get('nullable') is True


class TestReferenceEnums:
    """What a group is referenced as, and what its categories are."""

    def test_categories_are_extendable_options_of_the_object_group_type(self) -> None:
        """
        Not CmdbCategories, which is what the schema comment used to say

        The categories key holds public_ids of CmdbExtendableOptions filed under this option type, and
        deleting one of those options clears it from every group that used it.
        """
        assert CmdbObjectGroup.OPTION_TYPE is OptionType.OBJECT_GROUP

    def test_an_isms_reference_can_name_an_object_or_a_group(self) -> None:
        """The enum stored beside an IsmsRiskAssessment's object_id, deciding which of the two it is."""
        assert {member.value for member in ObjectReferenceType} == {'OBJECT', 'OBJECT_GROUP'}

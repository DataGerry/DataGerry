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
Unit tests for cmdb.framework.ipam.references

Covers resolve_special_type_id, the projection helper, the generic field-value finder, and the
three public lookups. The Mongo query filter shapes are pinned as part of the orchestrator
tests so a future refactor that loosens them fails loudly. ObjectsManager / TypesManager are
MagicMock stand-ins; the in-module helper resolve_special_type_id is exercised naturally rather
than patched, so the orchestrator and its helper are validated together
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField, VlanField, InterfaceField
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.references import (
    _find_objects_with_field_value,
    _project_to_reference_dicts,
    find_interfaces_referencing_subnet,
    find_subnets_referencing_supernet,
    find_vlans_referencing_subnet,
    resolve_special_type_id,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
VLAN_TYPE_ID: int = 12
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID: int = 200


def _make_full_object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a CmdbObject doc with extra fields that the projection helper should drop."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: [{CmdbObjectFieldKey.NAME: 'irrelevant', CmdbObjectFieldKey.VALUE: 'x'}],
        'extra_db_metadata': {'updated_at': '2026-01-01'},
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                            resolve_special_type_id                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_special_type_id_returns_none_when_no_matching_type_exists() -> None:
    """When the SpecialType has no CmdbType marked for it, the resolver returns None"""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    assert result is None
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


def test_resolve_special_type_id_returns_none_for_empty_dict() -> None:
    """An empty dict (falsy) from the manager is treated as 'no type found'"""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {}

    assert resolve_special_type_id(types_manager, SpecialType.VLAN) is None


def test_resolve_special_type_id_returns_public_id_from_matching_type_doc() -> None:
    """A matching CmdbType doc yields its public_id"""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    assert resolve_special_type_id(types_manager, SpecialType.SUBNET) == SUBNET_TYPE_ID


def test_resolve_special_type_id_returns_none_when_doc_has_no_public_id() -> None:
    """A type doc that is truthy but missing public_id yields None (rather than raising)"""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {'unrelated_key': 'value'}

    assert resolve_special_type_id(types_manager, SpecialType.SUBNET) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _project_to_reference_dicts                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_project_to_reference_dicts_returns_empty_for_empty_input() -> None:
    """An empty list of docs projects to an empty list"""
    assert _project_to_reference_dicts([]) == []


def test_project_to_reference_dicts_keeps_only_public_id_and_type_id() -> None:
    """All keys other than public_id and type_id are dropped during projection"""
    docs = [_make_full_object_doc(public_id=1, type_id=SUBNET_TYPE_ID)]

    projected = _project_to_reference_dicts(docs)

    assert projected == [{CmdbObjectKey.PUBLIC_ID: 1, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID}]


def test_project_to_reference_dicts_preserves_order_across_multiple_docs() -> None:
    """Multiple docs project in their original order"""
    docs = [
        _make_full_object_doc(public_id=3, type_id=SUBNET_TYPE_ID),
        _make_full_object_doc(public_id=1, type_id=SUBNET_TYPE_ID),
        _make_full_object_doc(public_id=2, type_id=VLAN_TYPE_ID),
    ]

    projected = _project_to_reference_dicts(docs)

    assert [d[CmdbObjectKey.PUBLIC_ID] for d in projected] == [3, 1, 2]
    assert [d[CmdbObjectKey.TYPE_ID] for d in projected] == [SUBNET_TYPE_ID, SUBNET_TYPE_ID, VLAN_TYPE_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _find_objects_with_field_value                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_objects_with_field_value_returns_empty_when_manager_returns_no_matches() -> None:
    """An empty result from find_objects yields an empty projection"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    result = _find_objects_with_field_value(
        objects_manager, SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, SUPERNET_OBJECT_ID,
    )

    assert result == []


def test_find_objects_with_field_value_projects_returned_docs_to_reference_shape() -> None:
    """Each returned doc is reduced to the lightweight {public_id, type_id} shape"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_full_object_doc(public_id=201, type_id=SUBNET_TYPE_ID),
        _make_full_object_doc(public_id=202, type_id=SUBNET_TYPE_ID),
    ]

    result = _find_objects_with_field_value(
        objects_manager, SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, SUPERNET_OBJECT_ID,
    )

    assert result == [
        {CmdbObjectKey.PUBLIC_ID: 201, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
        {CmdbObjectKey.PUBLIC_ID: 202, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
    ]


def test_find_objects_with_field_value_builds_type_scoped_elem_match_filter() -> None:
    """The find_objects call uses TYPE_ID + FIELDS $elemMatch with the given name+value"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    _find_objects_with_field_value(
        objects_manager, SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, SUPERNET_OBJECT_ID,
    )

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                    CmdbObjectFieldKey.VALUE: SUPERNET_OBJECT_ID,
                },
            },
        },
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                        find_subnets_referencing_supernet                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_subnets_referencing_supernet_returns_empty_when_subnet_type_not_defined() -> None:
    """Without a SUBNET CmdbType, the lookup short-circuits and never queries objects"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = find_subnets_referencing_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert result == []
    objects_manager.find_objects.assert_not_called()


def test_find_subnets_referencing_supernet_returns_empty_when_no_subnet_references_it() -> None:
    """A defined SUBNET type but no matching child subnets yields an empty list"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    result = find_subnets_referencing_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert result == []


def test_find_subnets_referencing_supernet_returns_projected_matching_subnets() -> None:
    """Matching child subnets are returned in the lightweight {public_id, type_id} shape"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_full_object_doc(public_id=201, type_id=SUBNET_TYPE_ID),
        _make_full_object_doc(public_id=202, type_id=SUBNET_TYPE_ID),
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    result = find_subnets_referencing_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert result == [
        {CmdbObjectKey.PUBLIC_ID: 201, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
        {CmdbObjectKey.PUBLIC_ID: 202, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
    ]
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                         find_vlans_referencing_subnet                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_vlans_referencing_subnet_returns_empty_when_vlan_type_not_defined() -> None:
    """Without a VLAN CmdbType, the lookup short-circuits and never queries objects"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = find_vlans_referencing_subnet(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert result == []
    objects_manager.find_objects.assert_not_called()


def test_find_vlans_referencing_subnet_returns_empty_when_no_vlan_references_it() -> None:
    """A defined VLAN type but no matching vlans yields an empty list"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = find_vlans_referencing_subnet(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert result == []


def test_find_vlans_referencing_subnet_returns_projected_matching_vlans() -> None:
    """Matching vlans are returned in the lightweight {public_id, type_id} shape"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_full_object_doc(public_id=301, type_id=VLAN_TYPE_ID),
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = find_vlans_referencing_subnet(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert result == [{CmdbObjectKey.PUBLIC_ID: 301, CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID}]
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN})


def test_find_vlans_referencing_subnet_queries_with_subnet_ref_field_filter() -> None:
    """The objects query filters by VLAN type_id and the SUBNET_REF field value"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    find_vlans_referencing_subnet(objects_manager, types_manager, SUBNET_OBJECT_ID)

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: VlanField.SUBNET_REF,
                    CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID,
                },
            },
        },
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                       find_interfaces_referencing_subnet                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_interfaces_referencing_subnet_returns_empty_when_no_matches() -> None:
    """No interface row references the subnet → empty projection"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    result = find_interfaces_referencing_subnet(objects_manager, SUBNET_OBJECT_ID)

    assert result == []


def test_find_interfaces_referencing_subnet_projects_matching_objects() -> None:
    """Matching CmdbObjects are returned in the lightweight {public_id, type_id} shape"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_full_object_doc(public_id=401, type_id=99),
        _make_full_object_doc(public_id=402, type_id=100),
    ]

    result = find_interfaces_referencing_subnet(objects_manager, SUBNET_OBJECT_ID)

    assert result == [
        {CmdbObjectKey.PUBLIC_ID: 401, CmdbObjectKey.TYPE_ID: 99},
        {CmdbObjectKey.PUBLIC_ID: 402, CmdbObjectKey.TYPE_ID: 100},
    ]


def test_find_interfaces_referencing_subnet_queries_with_nested_mds_elem_match_filter() -> None:
    """The objects query nests $elemMatch through multi_data_sections → values → data"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    find_interfaces_referencing_subnet(objects_manager, SUBNET_OBJECT_ID)

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.MULTI_DATA_SECTIONS: {
                '$elemMatch': {
                    CmdbObjectMdsKey.VALUES: {
                        '$elemMatch': {
                            CmdbObjectMdsRowKey.DATA: {
                                '$elemMatch': {
                                    CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                    CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID,
                                },
                            },
                        },
                    },
                },
            },
        },
        as_dict=True,
    )

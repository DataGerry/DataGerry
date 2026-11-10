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

Covers the special-type id lookups (one and several markers), the reference criteria builders, the
shared projected lookup (find_references / count_references / excluding_ids) and the three finders.
The Mongo filter shapes and the read options (projection, sort, limit) are pinned so a refactor that
loosens them - or reads whole documents again - fails loudly. ObjectsManager / TypesManager are
MagicMock stand-ins; the real projection and $nin semantics are exercised against MongoDB in
tests/integration/framework/test_integration_ipam_references.py
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
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
    IpamOverviewKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.references import (
    count_references,
    excluding_ids,
    find_interfaces_referencing_subnet,
    find_references,
    find_subnets_referencing_supernet,
    find_vlans_referencing_subnet,
    field_value_expr,
    interfaces_referencing_subnets_criteria,
    load_vlans_by_subnets,
    resolve_special_type_id,
    resolve_special_type_ids,
    subnets_referencing_supernets_criteria,
    vlans_referencing_subnets_criteria,
)
from cmdb.framework.ipam.references_constants import (
    REFERENCE_PROJECTION,
    REFERENCE_SORT,
    SPECIAL_TYPE_ID_PROJECTION,
    SPECIAL_TYPE_MARKER_PROJECTION,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
VLAN_TYPE_ID: int = 12
SUPERNET_TYPE_ID: int = 13
OTHER_SUPERNET_OBJECT_ID: int = 101
SELECTED_OBJECT_ID: int = 301
OTHER_SELECTED_OBJECT_ID: int = 302
CARRIER_TYPE_ID: int = 44
REFERENCE_COUNT: int = 37
READ_LIMIT: int = 21
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID: int = 200
SUBNET_OBJECT_ID_A: int = 201
SUBNET_OBJECT_ID_B: int = 202
VLAN_OBJECT_ID_X: int = 501
VLAN_OBJECT_ID_Y: int = 502
VLAN_OBJECT_ID_Z: int = 503
VLAN_NAME_X: str = 'VLAN-X'
VLAN_NAME_Y: str = 'VLAN-Y'
VLAN_NAME_Z: str = 'VLAN-Z'
MDS_ROW_DATA_PATH: str = 'multi_data_sections.values.data'


def _reference(public_id: Any, type_id: int) -> dict[str, Any]:
    """One projected reference document, as the database answers it."""
    return {CmdbObjectKey.PUBLIC_ID.value: public_id, CmdbObjectKey.TYPE_ID.value: type_id}


def _manager_answering(*documents: dict[str, Any]) -> MagicMock:
    """An ObjectsManager stand-in whose find_objects answers the given documents."""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = list(documents)

    return objects_manager


def _assert_projected_read(objects_manager: MagicMock, criteria: dict[str, Any], limit: int = 0) -> None:
    """The lookup read the two keys only, in ascending public_id, with the given limit."""
    objects_manager.find_objects.assert_called_once_with(
        criteria, as_dict=True, projection=REFERENCE_PROJECTION, limit=limit, sort=REFERENCE_SORT,
    )


def _make_vlan_doc(public_id: int, subnet_ref: Any, name: Any) -> dict[str, Any]:
    """Builds a VLAN CmdbObject doc with subnet-ref and name field entries."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID,
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: VlanField.SUBNET_REF, CmdbObjectFieldKey.VALUE: subnet_ref},
            {CmdbObjectFieldKey.NAME: VlanField.NAME, CmdbObjectFieldKey.VALUE: name},
        ],
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
    types_manager.get_one_by.assert_called_once_with(
        {TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET}, projection=SPECIAL_TYPE_ID_PROJECTION,
    )


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
#                                               resolve_special_type_ids                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_special_type_ids_reads_every_marker_in_one_projected_query() -> None:
    """Several markers cost one read of framework.types, projected to id + marker"""
    types_manager = MagicMock()
    types_manager.find.return_value = [
        {TypeSchemaKey.PUBLIC_ID.value: VLAN_TYPE_ID, TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.VLAN.value},
        {TypeSchemaKey.PUBLIC_ID.value: SUBNET_TYPE_ID, TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value},
    ]

    resolved = resolve_special_type_ids(types_manager, [SpecialType.SUBNET, SpecialType.VLAN, SpecialType.SUPERNET])

    assert resolved == {SpecialType.SUBNET: SUBNET_TYPE_ID, SpecialType.VLAN: VLAN_TYPE_ID, SpecialType.SUPERNET: None}
    types_manager.find.assert_called_once_with(
        criteria={TypeSchemaKey.SPECIAL_TYPE.value: {'$in': ['SUBNET', 'VLAN', 'SUPERNET']}},
        projection=SPECIAL_TYPE_MARKER_PROJECTION,
    )
    types_manager.get_one_by.assert_not_called()


def test_resolve_special_type_ids_keeps_the_first_type_of_a_marker() -> None:
    """Two types carrying one marker: the first read answers, as resolve_special_type_id does"""
    types_manager = MagicMock()
    types_manager.find.return_value = [
        {TypeSchemaKey.PUBLIC_ID.value: SUBNET_TYPE_ID, TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value},
        {TypeSchemaKey.PUBLIC_ID.value: VLAN_TYPE_ID, TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value},
    ]

    assert resolve_special_type_ids(types_manager, [SpecialType.SUBNET]) == {SpecialType.SUBNET: SUBNET_TYPE_ID}


def test_resolve_special_type_ids_asks_each_marker_once() -> None:
    """A repeated marker is asked once"""
    types_manager = MagicMock()
    types_manager.find.return_value = []

    resolve_special_type_ids(types_manager, [SpecialType.VLAN, SpecialType.VLAN])

    assert types_manager.find.call_args.kwargs['criteria'] == {
        TypeSchemaKey.SPECIAL_TYPE.value: {'$in': ['VLAN']},
    }


def test_resolve_special_type_ids_reads_nothing_for_no_marker() -> None:
    """No marker asked, no read"""
    types_manager = MagicMock()

    assert resolve_special_type_ids(types_manager, []) == {}
    types_manager.find.assert_not_called()


def test_resolve_special_type_ids_ignores_an_unknown_stored_marker() -> None:
    """A stored marker that is no SpecialType answers nothing"""
    types_manager = MagicMock()
    types_manager.find.return_value = [{TypeSchemaKey.PUBLIC_ID.value: SUBNET_TYPE_ID,
                                        TypeSchemaKey.SPECIAL_TYPE.value: 'NOT_A_MARKER'}]

    assert resolve_special_type_ids(types_manager, [SpecialType.SUBNET]) == {SpecialType.SUBNET: None}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  reference criteria                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_subnets_referencing_supernets_criteria_scopes_the_type_and_the_field_entry() -> None:
    """One $elemMatch on fields: the parent-supernet name AND one of the ids in the same entry"""
    criteria = subnets_referencing_supernets_criteria(SUBNET_TYPE_ID, [OTHER_SUPERNET_OBJECT_ID, SUPERNET_OBJECT_ID])

    assert criteria == {
        CmdbObjectKey.TYPE_ID.value: SUBNET_TYPE_ID,
        CmdbObjectKey.FIELDS.value: {'$elemMatch': {
            CmdbObjectFieldKey.NAME.value: SubnetField.PARENT_SUPERNET.value,
            CmdbObjectFieldKey.VALUE.value: {'$in': [SUPERNET_OBJECT_ID, OTHER_SUPERNET_OBJECT_ID]},
        }},
    }


def test_vlans_referencing_subnets_criteria_scopes_the_type_and_the_field_entry() -> None:
    """The VLAN filter names the VLAN type and the subnet-ref field"""
    criteria = vlans_referencing_subnets_criteria(VLAN_TYPE_ID, [SUBNET_OBJECT_ID_B, SUBNET_OBJECT_ID_A])

    assert criteria == {
        CmdbObjectKey.TYPE_ID.value: VLAN_TYPE_ID,
        CmdbObjectKey.FIELDS.value: {'$elemMatch': {
            CmdbObjectFieldKey.NAME.value: VlanField.SUBNET_REF.value,
            CmdbObjectFieldKey.VALUE.value: {'$in': [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]},
        }},
    }


def test_interfaces_referencing_subnets_criteria_is_scoped_to_the_interface_section() -> None:
    """Any type; the row must sit in the dg-ipam-interface section and name the subnet field"""
    criteria = interfaces_referencing_subnets_criteria([SUBNET_OBJECT_ID])

    assert criteria == {
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: {'$elemMatch': {
            CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
            CmdbObjectMdsKey.VALUES.value: {'$elemMatch': {
                CmdbObjectMdsRowKey.DATA.value: {'$elemMatch': {
                    CmdbObjectFieldKey.NAME.value: InterfaceField.SUBNET.value,
                    CmdbObjectFieldKey.VALUE.value: {'$in': [SUBNET_OBJECT_ID]},
                }},
            }},
        }},
    }
    assert CmdbObjectKey.TYPE_ID.value not in criteria


def test_excluding_ids_adds_a_public_id_exclusion() -> None:
    """The selection is AND-ed away, sorted"""
    base = vlans_referencing_subnets_criteria(VLAN_TYPE_ID, [SUBNET_OBJECT_ID])

    assert excluding_ids(base, {OTHER_SELECTED_OBJECT_ID, SELECTED_OBJECT_ID}) == {
        '$and': [base, {CmdbObjectKey.PUBLIC_ID.value: {'$nin': [SELECTED_OBJECT_ID, OTHER_SELECTED_OBJECT_ID]}}],
    }


def test_excluding_ids_leaves_the_filter_alone_without_a_selection() -> None:
    """No ids, the filter itself"""
    base = vlans_referencing_subnets_criteria(VLAN_TYPE_ID, [SUBNET_OBJECT_ID])

    assert excluding_ids(base, ()) is base


# -------------------------------------------------------------------------------------------------------------------- #
#                                          find_references / count_references                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_references_reads_two_keys_sorted_without_a_limit() -> None:
    """The documents are never read whole: projection, ascending public_id, no limit by default"""
    criteria = vlans_referencing_subnets_criteria(VLAN_TYPE_ID, [SUBNET_OBJECT_ID])
    objects_manager = _manager_answering(_reference(VLAN_OBJECT_ID_X, VLAN_TYPE_ID))

    found = find_references(objects_manager, criteria)

    assert found == [_reference(VLAN_OBJECT_ID_X, VLAN_TYPE_ID)]
    _assert_projected_read(objects_manager, criteria)


def test_find_references_passes_the_limit() -> None:
    """A capped read asks the database for at most that many"""
    criteria = interfaces_referencing_subnets_criteria([SUBNET_OBJECT_ID])
    objects_manager = _manager_answering()

    assert not find_references(objects_manager, criteria, limit=READ_LIMIT)
    _assert_projected_read(objects_manager, criteria, limit=READ_LIMIT)


def test_find_references_drops_documents_without_an_int_public_id() -> None:
    """A document without a usable public_id cannot be named - left out, not a KeyError"""
    objects_manager = _manager_answering(
        _reference(VLAN_OBJECT_ID_X, VLAN_TYPE_ID),
        {CmdbObjectKey.TYPE_ID.value: VLAN_TYPE_ID},
        _reference('503', VLAN_TYPE_ID),
        _reference(True, VLAN_TYPE_ID),
        _reference(VLAN_OBJECT_ID_Z, CARRIER_TYPE_ID),
    )

    found = find_references(objects_manager, {})

    assert found == [_reference(VLAN_OBJECT_ID_X, VLAN_TYPE_ID), _reference(VLAN_OBJECT_ID_Z, CARRIER_TYPE_ID)]


def test_count_references_counts_the_filter() -> None:
    """The count runs on the same filter, unscoped"""
    criteria = subnets_referencing_supernets_criteria(SUBNET_TYPE_ID, [SUPERNET_OBJECT_ID])
    objects_manager = MagicMock()
    objects_manager.count_objects.return_value = REFERENCE_COUNT

    assert count_references(objects_manager, criteria) == REFERENCE_COUNT
    objects_manager.count_objects.assert_called_once_with(criteria)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          find_subnets_referencing_supernet                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_subnets_referencing_supernet_returns_empty_when_subnet_type_not_defined() -> None:
    """No SUBNET type: nothing can reference the supernet, nothing is read"""
    objects_manager = MagicMock()

    assert find_subnets_referencing_supernet(objects_manager, None, SUPERNET_OBJECT_ID) == []
    objects_manager.find_objects.assert_not_called()


def test_find_subnets_referencing_supernet_reads_the_projected_subnets() -> None:
    """The subnets of the given type pointing at the supernet, two keys each"""
    objects_manager = _manager_answering(
        _reference(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID), _reference(SUBNET_OBJECT_ID_B, SUBNET_TYPE_ID),
    )

    found = find_subnets_referencing_supernet(objects_manager, SUBNET_TYPE_ID, SUPERNET_OBJECT_ID)

    assert found == [_reference(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID), _reference(SUBNET_OBJECT_ID_B, SUBNET_TYPE_ID)]
    _assert_projected_read(
        objects_manager, subnets_referencing_supernets_criteria(SUBNET_TYPE_ID, [SUPERNET_OBJECT_ID]),
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                            find_vlans_referencing_subnet                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_vlans_referencing_subnet_returns_empty_when_vlan_type_not_defined() -> None:
    """No VLAN type: nothing is read"""
    objects_manager = MagicMock()

    assert find_vlans_referencing_subnet(objects_manager, None, SUBNET_OBJECT_ID) == []
    objects_manager.find_objects.assert_not_called()


def test_find_vlans_referencing_subnet_reads_the_projected_vlans() -> None:
    """The VLANs of the given type pointing at the subnet, two keys each"""
    objects_manager = _manager_answering(_reference(VLAN_OBJECT_ID_Y, VLAN_TYPE_ID))

    found = find_vlans_referencing_subnet(objects_manager, VLAN_TYPE_ID, SUBNET_OBJECT_ID)

    assert found == [_reference(VLAN_OBJECT_ID_Y, VLAN_TYPE_ID)]
    _assert_projected_read(objects_manager, vlans_referencing_subnets_criteria(VLAN_TYPE_ID, [SUBNET_OBJECT_ID]))


# -------------------------------------------------------------------------------------------------------------------- #
#                                          find_interfaces_referencing_subnet                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_interfaces_referencing_subnet_reads_the_projected_carriers() -> None:
    """The carriers of any type, two keys each"""
    objects_manager = _manager_answering(_reference(SELECTED_OBJECT_ID, CARRIER_TYPE_ID))

    found = find_interfaces_referencing_subnet(objects_manager, SUBNET_OBJECT_ID)

    assert found == [_reference(SELECTED_OBJECT_ID, CARRIER_TYPE_ID)]
    _assert_projected_read(objects_manager, interfaces_referencing_subnets_criteria([SUBNET_OBJECT_ID]))


# -------------------------------------------------------------------------------------------------------------------- #
#                                             load_vlans_by_subnets                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_vlans_by_subnets_returns_empty_dict_for_empty_subnet_ids() -> None:
    """No subnet ids in → empty dict, no DB query, no type lookup"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    result = load_vlans_by_subnets(objects_manager, types_manager, [])

    assert result == {}
    objects_manager.aggregate_objects.assert_not_called()
    types_manager.get_one_by.assert_not_called()


def test_load_vlans_by_subnets_returns_empty_dict_when_vlan_type_not_defined() -> None:
    """No VLAN CmdbType → empty dict, no aggregation against objects"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = load_vlans_by_subnets(objects_manager, types_manager, [SUBNET_OBJECT_ID_A])

    assert result == {}
    objects_manager.aggregate_objects.assert_not_called()


def test_load_vlans_by_subnets_maps_grouped_rows_onto_their_subnet() -> None:
    """Each aggregation group ({_id, vlans}) lands under its subnet id unchanged"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = iter([
        {'_id': SUBNET_OBJECT_ID_A,
         IpamOverviewKey.VLANS: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}]},
        {'_id': SUBNET_OBJECT_ID_B,
         IpamOverviewKey.VLANS: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Y, IpamOverviewKey.NAME: VLAN_NAME_Y}]},
    ])
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = load_vlans_by_subnets(
        objects_manager, types_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
    )

    assert result == {
        SUBNET_OBJECT_ID_A: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}],
        SUBNET_OBJECT_ID_B: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Y, IpamOverviewKey.NAME: VLAN_NAME_Y}],
    }


def test_load_vlans_by_subnets_returns_per_subnet_lists_sorted_ascending_by_public_id() -> None:
    """Per-subnet buckets are surfaced in the ascending-by-public_id order the $sortArray stage
    produces server-side (the mock stands in for the already-sorted aggregation output)"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = iter([
        {'_id': SUBNET_OBJECT_ID_A, IpamOverviewKey.VLANS: [
            {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X},
            {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Y, IpamOverviewKey.NAME: VLAN_NAME_Y},
            {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Z, IpamOverviewKey.NAME: VLAN_NAME_Z},
        ]},
    ])
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = load_vlans_by_subnets(objects_manager, types_manager, [SUBNET_OBJECT_ID_A])

    public_ids = [vlan[CmdbObjectKey.PUBLIC_ID] for vlan in result[SUBNET_OBJECT_ID_A]]
    assert public_ids == sorted(public_ids)
    assert public_ids == [VLAN_OBJECT_ID_X, VLAN_OBJECT_ID_Y, VLAN_OBJECT_ID_Z]


def test_load_vlans_by_subnets_pins_the_aggregation_pipeline() -> None:
    """The pipeline matches, projects ref + name, re-filters, groups, then $sortArray-sorts
    each per-subnet bucket by public_id (no blocking pre-group $sort)"""
    objects_manager = MagicMock()
    objects_manager.aggregate_objects.return_value = iter([])
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}
    subnet_ids = [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]

    load_vlans_by_subnets(objects_manager, types_manager, subnet_ids)

    types_manager.get_one_by.assert_called_once_with(
        {TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN}, projection=SPECIAL_TYPE_ID_PROJECTION,
    )
    objects_manager.aggregate_objects.assert_called_once_with([
        {'$match': {
            CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: VlanField.SUBNET_REF,
                    CmdbObjectFieldKey.VALUE: {'$in': subnet_ids},
                },
            },
        }},
        {'$project': {
            '_id': 0,
            CmdbObjectKey.PUBLIC_ID: 1,
            VlanField.SUBNET_REF.value: field_value_expr(VlanField.SUBNET_REF),
            IpamOverviewKey.NAME: field_value_expr(VlanField.NAME),
        }},
        {'$match': {VlanField.SUBNET_REF.value: {'$in': subnet_ids}}},
        {'$group': {
            '_id': f'${VlanField.SUBNET_REF.value}',
            IpamOverviewKey.VLANS: {'$push': {
                CmdbObjectKey.PUBLIC_ID: '$public_id',
                IpamOverviewKey.NAME: '$name',
            }},
        }},
        {'$project': {
            IpamOverviewKey.VLANS: {'$sortArray': {
                'input': f'${IpamOverviewKey.VLANS.value}',
                'sortBy': {CmdbObjectKey.PUBLIC_ID.value: 1},
            }},
        }},
    ])


# -------------------------------------------------------------------------------------------------------------------- #
#                                               field_value_expr                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_field_value_expr_builds_the_first_value_extraction() -> None:
    """The expression filters by field name, maps to values, takes the first via $first, nulls when absent"""
    assert field_value_expr(VlanField.NAME) == {'$ifNull': [
        {'$first': {
            '$map': {
                'input': {'$filter': {
                    'input': '$fields',
                    'as': 'field',
                    'cond': {'$eq': ['$$field.name', VlanField.NAME]},
                }},
                'as': 'field',
                'in': '$$field.value',
            },
        }},
        None,
    ]}


def test_field_value_expr_targets_a_custom_array_path() -> None:
    """A non-empty array_path replaces the top-level 'fields' source with the given dotted path"""
    assert field_value_expr(InterfaceField.SUBNET, array_path=MDS_ROW_DATA_PATH) == {'$ifNull': [
        {'$first': {
            '$map': {
                'input': {'$filter': {
                    'input': f'${MDS_ROW_DATA_PATH}',
                    'as': 'field',
                    'cond': {'$eq': ['$$field.name', InterfaceField.SUBNET]},
                }},
                'as': 'field',
                'in': '$$field.value',
            },
        }},
        None,
    ]}

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
Reference lookups used by the IPAM deletion guards and overview builders

Most helpers return a list of lightweight dicts ({'public_id': int, 'type_id': int}) so the
caller can format a 400 response listing the blocking objects without needing to load full
CmdbObjects. The overview-oriented helpers (``load_vlans_by_subnets``) return a richer
{'public_id', 'name'} shape grouped by the queried subnet so the consumer can attach VLAN
chips next to subnet rows without an extra round-trip
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
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
# -------------------------------------------------------------------------------------------------------------------- #


def _project_to_reference_dicts(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Projects full CmdbObject documents down to the lightweight reference shape used by the
    deletion-guard responses

    Args:
        docs (list[dict[str, Any]]): Full CmdbObject documents (each must carry public_id and
            type_id at the top level)

    Returns:
        list[dict[str, Any]]: One dict per input with only the 'public_id' and 'type_id' keys
    """
    return [
        {
            CmdbObjectKey.PUBLIC_ID: doc[CmdbObjectKey.PUBLIC_ID],
            CmdbObjectKey.TYPE_ID: doc[CmdbObjectKey.TYPE_ID],
        }
        for doc in docs
    ]


def resolve_special_type_id(types_manager: TypesManager, special_type: SpecialType) -> int | None:
    """
    Returns the public_id of the CmdbType marked with the given SpecialType, or None if none exists

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType to resolve

    Returns:
        int | None: The CmdbType's public_id, or None if no such CmdbType is defined
    """
    type_doc: dict[str, Any] | None = types_manager.get_one_by({TypeSchemaKey.SPECIAL_TYPE: special_type})

    if not type_doc:
        return None

    return type_doc.get(CmdbObjectKey.PUBLIC_ID)


def _find_objects_with_field_value(
    objects_manager: ObjectsManager,
    type_id: int,
    field_name: str,
    field_value: Any,
) -> list[dict[str, Any]]:
    """
    Returns lightweight dicts for every CmdbObject of the given type whose 'fields' array
    contains an entry with the given name + value

    Uses '$elemMatch' on the top-level 'fields' array

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_id (int): The CmdbType's public_id to scope the query to
        field_name (str): The field 'name' to match
        field_value (Any): The field 'value' to match

    Returns:
        list[dict[str, Any]]: One dict per matching CmdbObject with 'public_id' and 'type_id'
    """
    criteria: dict[str, Any] = {
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: field_name,
                CmdbObjectFieldKey.VALUE: field_value,
            },
        },
    }

    matches: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return _project_to_reference_dicts(matches)


def field_value_expr(field_name: str, array_path: str = '') -> dict[str, Any]:
    """
    Builds the aggregation expression extracting the first value of a named name/value entry

    Filters a name/value entry array down to entries with the given name, maps them to
    their 'value' and takes the first element via $first; $ifNull turns a missing entry into
    an explicit None so projected documents always carry the key. Defaults to the document's
    top-level 'fields' array; pass ``array_path`` to target another entry array of the same
    shape (e.g. an unwound MDS row's 'data'). Compatible with the project-wide MongoDB 6.0
    floor

    Args:
        field_name (str): The entry name whose value is extracted
        array_path (str): Dotted document path of the name/value array (without the leading
            '$'); empty selects the top-level 'fields' array

    Returns:
        dict[str, Any]: The aggregation expression for use inside a $project stage
    """
    source_path: str = array_path or CmdbObjectKey.FIELDS.value

    return {'$ifNull': [
        {'$first': {
            '$map': {
                'input': {'$filter': {
                    'input': f'${source_path}',
                    'as': 'field',
                    'cond': {'$eq': [f'$$field.{CmdbObjectFieldKey.NAME.value}', field_name]},
                }},
                'as': 'field',
                'in': f'$$field.{CmdbObjectFieldKey.VALUE.value}',
            },
        }},
        None,
    ]}


def load_vlans_by_subnets(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """
    Groups VLAN CmdbObjects by the subnet their 'dg-subnet-ref' field points at

    A single aggregation selects every VLAN-typed CmdbObject whose 'dg-subnet-ref' is in
    ``subnet_ids``, extracts each VLAN's subnet reference and 'dg-name' (None when unset),
    groups the {'public_id', 'name'} entries server-side under their subnet and sorts each
    (small) per-subnet bucket by ascending public_id via $sortArray (MongoDB 6.0) - cheaper
    than the previous blocking $sort over the whole match set before grouping

    Returns an empty dict when no VLAN CmdbType is defined yet or no subnet_ids were supplied;
    subnets without referencing VLANs do not appear in the returned dict (callers should treat
    a missing key as an empty list)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_ids (list[int]): The subnet public_ids whose referencing VLANs should be loaded

    Returns:
        dict[int, list[dict[str, Any]]]: {subnet_id: [{public_id, name}, ...]} with each list
            sorted ascending by public_id
    """
    if not subnet_ids:
        return {}

    vlan_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.VLAN)

    if vlan_type_id is None:
        return {}

    subnet_ref_key: str = VlanField.SUBNET_REF.value
    pipeline: list[dict[str, Any]] = [
        {'$match': {
            CmdbObjectKey.TYPE_ID: vlan_type_id,
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
            subnet_ref_key: field_value_expr(VlanField.SUBNET_REF),
            IpamOverviewKey.NAME: field_value_expr(VlanField.NAME),
        }},
        {'$match': {subnet_ref_key: {'$in': subnet_ids}}},
        {'$group': {
            '_id': f'${subnet_ref_key}',
            IpamOverviewKey.VLANS: {'$push': {
                CmdbObjectKey.PUBLIC_ID: f'${CmdbObjectKey.PUBLIC_ID.value}',
                IpamOverviewKey.NAME: f'${IpamOverviewKey.NAME.value}',
            }},
        }},
        # Sort each per-subnet bucket instead of the whole match set ($sortArray: MongoDB 6.0)
        {'$project': {
            IpamOverviewKey.VLANS: {'$sortArray': {
                'input': f'${IpamOverviewKey.VLANS.value}',
                'sortBy': {CmdbObjectKey.PUBLIC_ID.value: 1},
            }},
        }},
    ]

    return {
        row['_id']: row[IpamOverviewKey.VLANS]
        for row in objects_manager.aggregate_objects(pipeline)
    }


def find_subnets_referencing_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns subnet CmdbObjects whose 'dg-supernet-ref' points at the given supernet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_object_id (int): public_id of the SUPERNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching subnet objects as {'public_id', 'type_id'} dicts; empty
            list when no SUBNET CmdbType exists or no subnet references the supernet
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    return _find_objects_with_field_value(
        objects_manager,
        subnet_type_id,
        SubnetField.PARENT_SUPERNET,
        supernet_object_id,
    )


def find_vlans_referencing_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns vlan CmdbObjects whose 'dg-subnet-ref' points at the given subnet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the SUBNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching vlan objects as {'public_id', 'type_id'} dicts; empty
            list when no VLAN CmdbType exists or no vlan references the subnet
    """
    vlan_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.VLAN)

    if vlan_type_id is None:
        return []

    return _find_objects_with_field_value(objects_manager, vlan_type_id, VlanField.SUBNET_REF, subnet_object_id)


def find_interfaces_referencing_subnet(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns CmdbObjects that have at least one 'dg-ipam-interface' MDS row whose
    'dg-interface-subnet' field points at the given subnet object

    Spans every CmdbType because the dg-ipam-interface section template is global. The
    $elemMatch is scoped to the dg-ipam-interface section (SECTION_ID), matching
    ``load_interface_owners`` - a row in some other section whose data happened to carry the
    same field name must not count as an interface reference

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the SUBNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching CmdbObjects as {'public_id', 'type_id'} dicts; empty
            list when no interface row references the subnet
    """
    criteria: dict[str, Any] = {
        CmdbObjectKey.MULTI_DATA_SECTIONS: {
            '$elemMatch': {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: {
                    '$elemMatch': {
                        CmdbObjectMdsRowKey.DATA: {
                            '$elemMatch': {
                                CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                CmdbObjectFieldKey.VALUE: subnet_object_id,
                            },
                        },
                    },
                },
            },
        },
    }

    matches: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return _project_to_reference_dicts(matches)

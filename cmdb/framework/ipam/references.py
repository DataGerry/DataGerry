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
Reference lookups used by the IPAM delete guards, the CI Explorer and the overview builders

The IPAM hierarchy is not stored as object relations but as references inside objects: a SUBNET's
``dg-supernet-ref`` field, a VLAN's ``dg-subnet-ref`` field and the ``dg-interface-subnet`` field of a
``dg-ipam-interface`` multi-data-section row. The lookups here answer "which objects point at these
ids":

* the criteria builders (``*_criteria``) state each reference as a filter over ``framework.objects``,
  for one or many referenced ids at once
* ``find_references`` / ``count_references`` run such a filter and read only ``public_id`` and
  ``type_id`` of each match (``REFERENCE_PROJECTION``) - a referencing object is never loaded whole
* the ``find_*_referencing_*`` finders combine the two for one referenced object, as the CI Explorer
  walks it

None of them applies an ACL: the delete guards enforce an invariant over every stored object, not
only over what the caller may read (see ``ObjectsManager.find_objects``). The overview helper
(``load_vlans_by_subnets``) answers a richer {'public_id', 'name'} shape grouped by subnet instead
"""
from collections.abc import Collection, Iterable
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.utils import Builder
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
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.framework.ipam.references_constants import (
    REFERENCE_PROJECTION,
    REFERENCE_SORT,
    SPECIAL_TYPE_ID_PROJECTION,
    SPECIAL_TYPE_MARKER_PROJECTION,
)
# -------------------------------------------------------------------------------------------------------------------- #


def excluding_ids(criteria: dict[str, Any], exclude_ids: Collection[int]) -> dict[str, Any]:
    """
    Narrows a reference filter to the objects outside a set of ids

    A delete selection does not block itself: the objects being deleted together with the one they
    reference are left out of the filter, so a supernet and all of its subnets go in one request

    Args:
        criteria (dict[str, Any]): A reference filter (one of the ``*_criteria`` builders)
        exclude_ids (Collection[int]): public_ids that do not count as referencing; empty adds nothing

    Returns:
        dict[str, Any]: The filter, AND-ed with ``public_id $nin exclude_ids`` when any are given
    """
    if not exclude_ids:
        return criteria

    return {'$and': [criteria, {CmdbObjectKey.PUBLIC_ID.value: {'$nin': sorted(exclude_ids)}}]}


def find_references(objects_manager: ObjectsManager, criteria: dict[str, Any], limit: int = 0) -> list[dict[str, Any]]:
    """
    The objects matching a reference filter, as {'public_id', 'type_id'} dicts in ascending public_id

    Reads the two keys only (``REFERENCE_PROJECTION``), never the whole document, and no ACL (see the
    module docstring). A stored document without an integer public_id is left out: it cannot be named
    in a message, and an object without one is unreadable everywhere else too

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        criteria (dict[str, Any]): A reference filter (one of the ``*_criteria`` builders)
        limit (int): The most objects read; 0 (the default) reads every match

    Raises:
        ObjectsManagerGetError: When the objects could not be read

    Returns:
        list[dict[str, Any]]: One {'public_id', 'type_id'} dict per matching object
    """
    matches: list[dict[str, Any]] = objects_manager.find_objects(
        criteria, as_dict=True, projection=REFERENCE_PROJECTION, limit=limit, sort=REFERENCE_SORT,
    )

    return [match for match in matches if _has_int_public_id(match)]


def count_references(objects_manager: ObjectsManager, criteria: dict[str, Any]) -> int:
    """
    How many objects match a reference filter - for the "... and N more" of a capped list

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        criteria (dict[str, Any]): A reference filter (one of the ``*_criteria`` builders)

    Raises:
        ObjectsManagerGetError: When the count failed

    Returns:
        int: The number of matching objects
    """
    return objects_manager.count_objects(criteria)


def _has_int_public_id(document: dict[str, Any]) -> bool:
    """Whether a document carries an integer public_id (a bool is not one)"""
    public_id: Any = document.get(CmdbObjectKey.PUBLIC_ID.value)

    return isinstance(public_id, int) and not isinstance(public_id, bool)


def resolve_special_type_document(
    types_manager: TypesManager,
    special_type: SpecialType,
) -> dict[str, Any] | None:
    """
    Returns the stored CmdbType document marked with the given SpecialType, or None if none exists

    The callers that only need the public_id go through ``resolve_special_type_id``; this one exists
    for the callers that need something else off the same document - the ACL, for instance - so they
    do not query the same type twice

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType to resolve

    Returns:
        dict[str, Any] | None: The CmdbType document, or None if no such CmdbType is defined
    """
    return types_manager.get_one_by({TypeSchemaKey.SPECIAL_TYPE: special_type})


def resolve_special_type_id(types_manager: TypesManager, special_type: SpecialType) -> int | None:
    """
    Returns the public_id of the CmdbType marked with the given SpecialType, or None if none exists

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType to resolve

    Returns:
        int | None: The CmdbType's public_id, or None if no such CmdbType is defined
    """
    type_doc: dict[str, Any] | None = types_manager.get_one_by(
        {TypeSchemaKey.SPECIAL_TYPE: special_type}, projection=SPECIAL_TYPE_ID_PROJECTION,
    )

    if not type_doc:
        return None

    return type_doc.get(CmdbObjectKey.PUBLIC_ID)


def resolve_special_type_ids(
        types_manager: TypesManager,
        special_types: Iterable[SpecialType]) -> dict[SpecialType, int | None]:
    """
    The public_ids of the CmdbTypes marked with several SpecialTypes, in one read

    For a caller that needs more than one of them (the CI Explorer's SUPERNET / SUBNET / VLAN, the
    delete guard's SUBNET / VLAN): one projected query instead of one per marker. When more than one
    type carries a marker, the first one read answers, as ``resolve_special_type_id`` does

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_types (Iterable[SpecialType]): The markers to resolve

    Raises:
        BaseManagerGetError: When the types could not be read

    Returns:
        dict[SpecialType, int | None]: Every asked marker, None where no CmdbType carries it
    """
    wanted: list[SpecialType] = list(dict.fromkeys(special_types))
    resolved: dict[SpecialType, int | None] = dict.fromkeys(wanted)

    if not wanted:
        return resolved

    type_docs: list[dict[str, Any]] = types_manager.find(
        criteria={TypeSchemaKey.SPECIAL_TYPE.value: {'$in': [marker.value for marker in wanted]}},
        projection=SPECIAL_TYPE_MARKER_PROJECTION,
    )

    for type_doc in type_docs:
        marker: Any = type_doc.get(TypeSchemaKey.SPECIAL_TYPE.value)

        if SpecialType.is_valid(marker) and resolved.get(SpecialType(marker)) is None:
            resolved[SpecialType(marker)] = type_doc.get(TypeSchemaKey.PUBLIC_ID.value)

    return resolved


def resolve_special_type_icon(types_manager: TypesManager, special_type: SpecialType) -> str | None:
    """
    Returns the icon of the CmdbType marked with the given SpecialType, or None if none exists

    Reads the type's render_meta icon (the same icon shown for the type elsewhere). Returns None
    when no CmdbType carries the SpecialType yet or the type has no icon set, so callers pass the
    value through to the frontend, which applies its own default

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType to resolve (SUPERNET / SUBNET)

    Returns:
        str | None: The CmdbType's icon, or None when unresolved / unset
    """
    type_doc: dict[str, Any] | None = types_manager.get_one_by({TypeSchemaKey.SPECIAL_TYPE: special_type})

    if not type_doc:
        return None

    return CmdbType.from_data(type_doc).get_icon()


def _field_reference_criteria(type_id: int, field_name: str, referenced_ids: Collection[int]) -> dict[str, Any]:
    """
    The filter selecting the objects of one type whose named top-level field references any of the ids

    Uses '$elemMatch' on the top-level 'fields' array, so the name and the value must sit in the same
    entry (index ``fields_name_value``)

    Args:
        type_id (int): The CmdbType's public_id to scope the query to
        field_name (str): The field 'name' to match
        referenced_ids (Collection[int]): The referenced public_ids; one match is enough

    Returns:
        dict[str, Any]: The filter for ``framework.objects``
    """
    return {
        CmdbObjectKey.TYPE_ID.value: type_id,
        CmdbObjectKey.FIELDS.value: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME.value: field_name,
                CmdbObjectFieldKey.VALUE.value: {'$in': sorted(referenced_ids)},
            },
        },
    }


def subnets_referencing_supernets_criteria(subnet_type_id: int, supernet_ids: Collection[int]) -> dict[str, Any]:
    """
    The filter selecting the SUBNET objects whose 'dg-supernet-ref' points at any of the supernets

    Args:
        subnet_type_id (int): public_id of the SUBNET CmdbType
        supernet_ids (Collection[int]): public_ids of the SUPERNET objects

    Returns:
        dict[str, Any]: The filter for ``framework.objects``
    """
    return _field_reference_criteria(subnet_type_id, SubnetField.PARENT_SUPERNET.value, supernet_ids)


def vlans_referencing_subnets_criteria(vlan_type_id: int, subnet_ids: Collection[int]) -> dict[str, Any]:
    """
    The filter selecting the VLAN objects whose 'dg-subnet-ref' points at any of the subnets

    Args:
        vlan_type_id (int): public_id of the VLAN CmdbType
        subnet_ids (Collection[int]): public_ids of the SUBNET objects

    Returns:
        dict[str, Any]: The filter for ``framework.objects``
    """
    return _field_reference_criteria(vlan_type_id, VlanField.SUBNET_REF.value, subnet_ids)


def interfaces_referencing_subnets_criteria(subnet_ids: Collection[int]) -> dict[str, Any]:
    """
    The filter selecting the objects with a 'dg-ipam-interface' row whose 'dg-interface-subnet' points at any subnet

    Spans every CmdbType because the dg-ipam-interface section template is global. The $elemMatch is
    scoped to the dg-ipam-interface section (SECTION_ID), matching ``load_interface_owners`` - a row in
    some other section whose data happened to carry the same field name must not count as an interface
    reference (index ``multi_data_sections_values_data_name_value``)

    Args:
        subnet_ids (Collection[int]): public_ids of the SUBNET objects

    Returns:
        dict[str, Any]: The filter for ``framework.objects``
    """
    return {
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: {
            '$elemMatch': {
                CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
                CmdbObjectMdsKey.VALUES.value: {
                    '$elemMatch': {
                        CmdbObjectMdsRowKey.DATA.value: {
                            '$elemMatch': {
                                CmdbObjectFieldKey.NAME.value: InterfaceField.SUBNET.value,
                                CmdbObjectFieldKey.VALUE.value: {'$in': sorted(subnet_ids)},
                            },
                        },
                    },
                },
            },
        },
    }


def field_value_expr(field_name: str, array_path: str = '') -> dict[str, Any]:
    """
    Builds the aggregation expression extracting the first value of a named name/value entry

    Filters a name/value entry array down to entries with the given name, maps them to
    their 'value' and takes the first element via $first; $ifNull turns a missing entry into
    an explicit None so projected documents always carry the key. Defaults to the document's
    top-level 'fields' array; pass ``array_path`` to target another entry array of the same
    shape (e.g. an unwound MDS row's 'data'). Compatible with the project-wide MongoDB 7.0
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
    (small) per-subnet bucket by ascending public_id via $sortArray (MongoDB 5.2+) - cheaper
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
        Builder.match_({
            CmdbObjectKey.TYPE_ID: vlan_type_id,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: VlanField.SUBNET_REF,
                    CmdbObjectFieldKey.VALUE: {'$in': subnet_ids},
                },
            },
        }),
        Builder.project_({
            '_id': 0,
            CmdbObjectKey.PUBLIC_ID: 1,
            subnet_ref_key: field_value_expr(VlanField.SUBNET_REF),
            IpamOverviewKey.NAME: field_value_expr(VlanField.NAME),
        }),
        Builder.match_({subnet_ref_key: {'$in': subnet_ids}}),
        Builder.group_(f'${subnet_ref_key}', {
            IpamOverviewKey.VLANS: {'$push': {
                CmdbObjectKey.PUBLIC_ID: f'${CmdbObjectKey.PUBLIC_ID.value}',
                IpamOverviewKey.NAME: f'${IpamOverviewKey.NAME.value}',
            }},
        }),
        # Sort each per-subnet bucket instead of the whole match set ($sortArray: MongoDB 5.2+)
        Builder.project_({
            IpamOverviewKey.VLANS: {'$sortArray': {
                'input': f'${IpamOverviewKey.VLANS.value}',
                'sortBy': {CmdbObjectKey.PUBLIC_ID.value: 1},
            }},
        }),
    ]

    return {
        row['_id']: row[IpamOverviewKey.VLANS]
        for row in objects_manager.aggregate_objects(pipeline)
    }


def find_subnets_referencing_supernet(
    objects_manager: ObjectsManager,
    subnet_type_id: int | None,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns the subnet CmdbObjects whose 'dg-supernet-ref' points at the given supernet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_type_id (int | None): public_id of the SUBNET CmdbType, as the caller resolved it; None
            when no such type exists
        supernet_object_id (int): public_id of the SUPERNET CmdbObject

    Returns:
        list[dict[str, Any]]: Matching subnet objects as {'public_id', 'type_id'} dicts; empty
            list when no SUBNET CmdbType exists or no subnet references the supernet
    """
    if subnet_type_id is None:
        return []

    criteria: dict[str, Any] = subnets_referencing_supernets_criteria(subnet_type_id, [supernet_object_id])

    return find_references(objects_manager, criteria)


def find_vlans_referencing_subnet(
    objects_manager: ObjectsManager,
    vlan_type_id: int | None,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns the vlan CmdbObjects whose 'dg-subnet-ref' points at the given subnet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        vlan_type_id (int | None): public_id of the VLAN CmdbType, as the caller resolved it; None when
            no such type exists
        subnet_object_id (int): public_id of the SUBNET CmdbObject

    Returns:
        list[dict[str, Any]]: Matching vlan objects as {'public_id', 'type_id'} dicts; empty
            list when no VLAN CmdbType exists or no vlan references the subnet
    """
    if vlan_type_id is None:
        return []

    return find_references(objects_manager, vlans_referencing_subnets_criteria(vlan_type_id, [subnet_object_id]))


def find_interfaces_referencing_subnet(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns the CmdbObjects with at least one 'dg-ipam-interface' row whose 'dg-interface-subnet' points at the subnet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the SUBNET CmdbObject

    Returns:
        list[dict[str, Any]]: Matching CmdbObjects as {'public_id', 'type_id'} dicts; empty
            list when no interface row references the subnet
    """
    return find_references(objects_manager, interfaces_referencing_subnets_criteria([subnet_object_id]))

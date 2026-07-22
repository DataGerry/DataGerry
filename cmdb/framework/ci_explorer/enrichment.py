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
Batched field-flatten enrichment for the CI Explorer

Replaces the per-call ``get_summary_line`` / ``get_location`` lookups inside the route's
per-object enrichment loop with two bulk ``$in`` queries computed once across the full
set of objects that will appear in the response (root, linked, location-grafted).
Also replaces the per-call ``is_ref_field`` (which round-trips to fetch the type) with
an in-memory lookup against the already-loaded type metadata

The flatten function returns enriched copies (the field list is rebuilt), avoiding the
in-place mutation of manager-returned dicts the route does today
"""
from typing import Any, Iterable, Mapping

from cmdb.manager import LocationsManager, ObjectsManager
# -------------------------------------------------------------------------------------------------------------------- #

DG_LOCATION_FIELD_NAME: str = 'dg_location'
REF_FIELD_TYPE: str = 'ref'


def collect_ref_field_names(type_doc: dict[str, Any]) -> set[str]:
    """
    Returns the field names declared as type=='ref' on a CmdbType document

    Replaces the per-field ``objects_manager.is_ref_field(...)`` round-trip used in the
    route today. The caller derives this set once per type via the already-loaded
    ``types_by_id`` map and reuses it across every object of that type. Matches the
    existing ``is_ref_field`` contract: only the plain 'ref' field type is recognised
    (other ref-like types are not included so behaviour stays parity)

    Args:
        type_doc (dict[str, Any]): A CmdbType document as stored in framework.types

    Returns:
        set[str]: Field names of every entry whose 'type' is exactly 'ref'
    """
    return {
        field.get('name')
        for field in type_doc.get('fields', []) or []
        if field.get('type') == REF_FIELD_TYPE and field.get('name')
    }


def collect_ref_and_location_ids(
    objects: Iterable[dict[str, Any]],
    types_by_id: Mapping[int, dict[str, Any]],
) -> tuple[set[int], set[int]]:
    """
    Walks every object once and collects the referenced public_ids that need batch resolution

    For each object, finds the ref-typed field names from its CmdbType (via ``types_by_id``)
    and collects the integer public_ids stored in those fields. Separately, collects every
    integer value stored in a ``dg_location`` field. Non-integer values are skipped (matches
    the linked-object guard the route uses today, generalised to all objects)

    Args:
        objects (Iterable[dict[str, Any]]): CmdbObject documents that will appear in the
            response (root, linked, location-grafted)
        types_by_id (Mapping[int, dict[str, Any]]): {type_id: type_doc} for every CmdbType
            referenced by ``objects``; objects whose type_id is absent yield nothing

    Returns:
        tuple[set[int], set[int]]: (referenced object public_ids, referenced location public_ids)
    """
    ref_ids: set[int] = set()
    location_ids: set[int] = set()

    for obj in objects:
        type_doc: dict[str, Any] | None = types_by_id.get(obj.get('type_id'))

        if type_doc is None:
            continue

        ref_field_names: set[str] = collect_ref_field_names(type_doc)

        for field in obj.get('fields', []) or []:
            value: Any = field.get('value')

            if not isinstance(value, int):
                continue

            field_name: Any = field.get('name')

            if field_name in ref_field_names:
                ref_ids.add(value)

            if field_name == DG_LOCATION_FIELD_NAME:
                location_ids.add(value)

    return ref_ids, location_ids


def build_summary_lookup(
    objects_manager: ObjectsManager,
    ref_ids: set[int],
) -> dict[int, str]:
    """
    Resolves a batch of ref public_ids to summary lines in two Mongo queries

    Wraps ``objects_manager.get_summary_lines_lookup`` so the enrichment module owns the
    full lookup contract: empty set short-circuits to an empty map without touching the
    DB. Missing keys in the returned map mean the referenced object was deleted or the
    type no longer resolves - the caller falls back to keeping the raw int value

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        ref_ids (set[int]): public_ids of referenced CmdbObjects to resolve

    Returns:
        dict[int, str]: {public_id: summary_line} for every resolvable ref id; possibly
            smaller than ``ref_ids`` when some refs are dangling
    """
    if not ref_ids:
        return {}

    return objects_manager.get_summary_lines_lookup(list(ref_ids))


def build_location_name_lookup(
    locations_manager: LocationsManager,
    location_ids: set[int],
) -> dict[int, str]:
    """
    Resolves a batch of location public_ids to their display names in one Mongo query

    Mirrors ``build_summary_lookup`` for the dg_location side: one ``$in`` over the
    framework.locations collection, mapped down to ``{public_id: name}``. Replaces the
    per-call ``locations_manager.get_location`` round-trip in the current enrichment loop

    Args:
        locations_manager (LocationsManager): db interface for CmdbLocations
        location_ids (set[int]): public_ids of CmdbLocations to resolve

    Returns:
        dict[int, str]: {public_id: name} for every resolvable location id; ids that
            no longer exist are absent from the returned map
    """
    if not location_ids:
        return {}

    docs: list[dict[str, Any]] = locations_manager.find(
        criteria={'public_id': {'$in': list(location_ids)}},
    )

    return {
        doc['public_id']: doc['name']
        for doc in docs
        if isinstance(doc.get('public_id'), int) and isinstance(doc.get('name'), str)
    }


def flatten_object_fields(
    obj: dict[str, Any],
    types_by_id: Mapping[int, dict[str, Any]],
    summary_lookup: Mapping[int, str],
    location_lookup: Mapping[int, str],
) -> dict[str, Any]:
    """
    Returns an enriched copy of ``obj`` with ref values replaced by summary lines and
    ``dg_location`` values replaced by location names

    The original document is left untouched (no in-place mutation of manager-returned
    dicts). When a referenced id is missing from its lookup map (e.g. the target was
    deleted) the raw int value is kept - the caller never sees a None or a placeholder
    string. Values that are not integers are also passed through unchanged, matching
    the linked-object guard the route uses today

    Args:
        obj (dict[str, Any]): The CmdbObject document to enrich
        types_by_id (Mapping[int, dict[str, Any]]): {type_id: type_doc} for resolving the
            object's ref field names
        summary_lookup (Mapping[int, str]): {ref_object_id: summary_line} from
            ``build_summary_lookup``
        location_lookup (Mapping[int, str]): {location_id: name} from
            ``build_location_name_lookup``

    Returns:
        dict[str, Any]: Shallow copy of ``obj`` with a rebuilt ``fields`` list; every
            other top-level key is preserved by reference
    """
    type_doc: dict[str, Any] | None = types_by_id.get(obj.get('type_id'))
    ref_field_names: set[str] = collect_ref_field_names(type_doc) if type_doc is not None else set()

    new_fields: list[dict[str, Any]] = []

    for field in obj.get('fields', []) or []:
        field_name: Any = field.get('name')
        value: Any = field.get('value')
        new_field: dict[str, Any] = dict(field)

        if isinstance(value, int):
            if field_name in ref_field_names and value in summary_lookup:
                new_field['value'] = summary_lookup[value]
            elif field_name == DG_LOCATION_FIELD_NAME and value in location_lookup:
                new_field['value'] = location_lookup[value]

        new_fields.append(new_field)

    enriched: dict[str, Any] = dict(obj)
    enriched['fields'] = new_fields

    return enriched

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
Node payload composers for the CI Explorer

One ``compose_node`` builder used everywhere - root, relation-linked, location-grafted -
so the wire shape stays consistent across branches (the route previously had three
copies with subtly different defensive dict access; see B3 in the refactor audit). Title
resolution and type_info shaping are factored into their own helpers so unit tests can
exercise them without constructing a full object
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

CI_EXPLORER_LABEL_KEY: str = 'ci_explorer_label'
CI_EXPLORER_COLOR_KEY: str = 'ci_explorer_color'


def resolve_title(obj: dict[str, Any], type_doc: dict[str, Any]) -> Any:
    """
    Returns the value of the field that the CmdbType nominates as its CI Explorer title

    The type's ``ci_explorer_label`` is the *name* of a field on the object (not the
    value). When that field is found on the object, its value is returned as-is (after
    any enrichment the caller already applied). Returns None when the type does not
    nominate a label, or when the nominated field is absent from the object

    Args:
        obj (dict[str, Any]): The CmdbObject document
        type_doc (dict[str, Any]): The CmdbType document whose ``ci_explorer_label``
            points at the field to read

    Returns:
        Any: The value of the configured title field, or None when not resolvable
    """
    label_field_name: Any = type_doc.get(CI_EXPLORER_LABEL_KEY)

    if not label_field_name:
        return None

    for field in obj.get('fields', []) or []:
        if field.get('name') == label_field_name:
            return field.get('value')

    return None


def build_type_info(type_doc: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the ``type_info`` block emitted next to every CI Explorer node

    Single source of truth for this nested dict so the response stays identical across
    root / relation / location branches and a CmdbType missing ``render_meta`` no longer
    crashes the route (the previous bare ``['render_meta'].get('icon')`` raised KeyError,
    swallowed into a 500 by the catch-all). All five keys are always present; values
    fall through to None when the type omits them

    Args:
        type_doc (dict[str, Any]): The CmdbType document

    Returns:
        dict[str, Any]: ``{type_id, type_color, label, icon, fields}`` with stable keys
    """
    return {
        'type_id': type_doc.get('public_id'),
        'type_color': type_doc.get(CI_EXPLORER_COLOR_KEY),
        'label': type_doc.get('label'),
        'icon': (type_doc.get('render_meta') or {}).get('icon'),
        'fields': type_doc.get('fields', []) or [],
    }


def compose_node(
    linked_object: dict[str, Any],
    type_doc: dict[str, Any],
    relation_color: str | None,
) -> dict[str, Any]:
    """
    Builds one node dict for the CI Explorer response

    Used for the root node (with relation_color=None), each relation neighbour (with
    the per-direction color from the CmdbRelation), and each location-grafted neighbour
    (with the fixed CHILD_LOCATION_REL_COLOR / PARENT_LOCATION_REL_COLOR). Caller is
    responsible for having already enriched the object's fields (refs to summary lines,
    dg_location to location name)

    Args:
        linked_object (dict[str, Any]): The (already-enriched) CmdbObject document
        type_doc (dict[str, Any]): The CmdbType document for ``linked_object``
        relation_color (str | None): The color string to attach to this node; None for
            the root node

    Returns:
        dict[str, Any]: ``{linked_object, title, type_info, relation_color}``
    """
    return {
        'linked_object': linked_object,
        'title': resolve_title(linked_object, type_doc),
        'type_info': build_type_info(type_doc),
        'relation_color': relation_color,
    }

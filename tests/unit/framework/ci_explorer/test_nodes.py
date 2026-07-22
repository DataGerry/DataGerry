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
Unit tests for cmdb.framework.ci_explorer.nodes
"""
from typing import Any

from cmdb.framework.ci_explorer.nodes import build_type_info, compose_node, resolve_title
# -------------------------------------------------------------------------------------------------------------------- #


def _type_doc(public_id: int = 10) -> dict[str, Any]:
    """Builds a CmdbType document with every field the CI Explorer reads."""
    return {
        'public_id': public_id,
        'label': 'Server',
        'ci_explorer_label': 'name',
        'ci_explorer_color': '#1f77b4',
        'render_meta': {'icon': 'fa-server'},
        'fields': [{'name': 'name', 'type': 'text'}],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  resolve_title                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_title_returns_value_of_configured_label_field() -> None:
    """Returns the value of the field nominated by the type's ci_explorer_label"""
    obj = {'fields': [{'name': 'name', 'value': 'srv-01'}]}

    assert resolve_title(obj, _type_doc()) == 'srv-01'


def test_resolve_title_returns_none_when_type_has_no_label() -> None:
    """Returns None when ci_explorer_label is missing or empty on the type"""
    type_doc = _type_doc()
    type_doc['ci_explorer_label'] = None
    obj = {'fields': [{'name': 'name', 'value': 'srv-01'}]}

    assert resolve_title(obj, type_doc) is None


def test_resolve_title_returns_none_when_label_field_absent_from_object() -> None:
    """Returns None when the configured label field isn't on the object"""
    obj = {'fields': [{'name': 'hostname', 'value': 'srv-01'}]}

    assert resolve_title(obj, _type_doc()) is None


def test_resolve_title_finds_the_label_among_multiple_fields() -> None:
    """Walks the field list and returns the first matching name's value"""
    obj = {'fields': [
        {'name': 'serial', 'value': 'X-123'},
        {'name': 'name', 'value': 'srv-01'},
        {'name': 'location', 'value': 'eu-west'},
    ]}

    assert resolve_title(obj, _type_doc()) == 'srv-01'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 build_type_info                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_type_info_emits_full_shape_from_complete_type_doc() -> None:
    """Every key is populated when the type carries the corresponding attribute"""
    info = build_type_info(_type_doc())

    assert info == {
        'type_id': 10,
        'type_color': '#1f77b4',
        'label': 'Server',
        'icon': 'fa-server',
        'fields': [{'name': 'name', 'type': 'text'}],
    }


def test_build_type_info_handles_missing_render_meta_without_keyerror() -> None:
    """B3 fix: a type doc without render_meta no longer raises; icon falls through to None"""
    type_doc = _type_doc()
    del type_doc['render_meta']

    info = build_type_info(type_doc)

    assert info['icon'] is None
    assert info['type_id'] == 10  # other fields unaffected


def test_build_type_info_handles_missing_ci_explorer_color_as_none() -> None:
    """A type without ci_explorer_color reports type_color=None rather than raising"""
    type_doc = _type_doc()
    del type_doc['ci_explorer_color']

    info = build_type_info(type_doc)

    assert info['type_color'] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  compose_node                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_node_emits_full_node_shape() -> None:
    """Pins the four wire-level keys on a composed node"""
    obj = {'fields': [{'name': 'name', 'value': 'srv-01'}]}

    node = compose_node(obj, _type_doc(), relation_color='#33aa33')

    assert node['linked_object'] is obj
    assert node['title'] == 'srv-01'
    assert node['type_info']['type_id'] == 10
    assert node['relation_color'] == '#33aa33'


def test_compose_node_emits_none_relation_color_for_root() -> None:
    """The root node convention is relation_color=None; the composer honors that verbatim"""
    obj = {'fields': [{'name': 'name', 'value': 'srv-root'}]}

    node = compose_node(obj, _type_doc(), relation_color=None)

    assert node['relation_color'] is None

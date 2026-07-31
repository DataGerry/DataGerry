# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.framework.exporter.export_template_helper

Pins the header of an object-import template: the self-describing column layout
(``<Field label> [MDS-<Section label>] [<field name>]``), the fallbacks for a field without a label and
a section without one, and the column ORDER - identity columns, then the regular fields in section
order, then the multi-data-section fields grouped per section, mirroring an object CSV export of the
same type. Also pins the two properties a template must never lose: a field no section places still
gets a column, and a field placed twice gets exactly one.
"""
from typing import Any

import pytest

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.framework.exporter.export_template_helper import (
    build_field_label_map,
    build_object_template_header,
    build_template_column,
    collect_template_field_layout,
    type_has_template_fields,
)
# -------------------------------------------------------------------------------------------------------------------- #

IDENTITY_COLUMNS: list[str] = ['Public ID [public_id]', 'Active [active]']

REGULAR_SECTION: str = 'main'
MDS_SECTION: str = 'ifaces'
MDS_SECTION_LABEL: str = 'Network Interfaces'


def _field(name: str, label: str | None = None, field_type: str = 'text') -> dict[str, Any]:
    """Builds one CmdbType field entry."""
    entry: dict[str, Any] = {'type': field_type, 'name': name}

    if label is not None:
        entry['label'] = label

    return entry


def _section(name: str, fields: list[str], label: str | None = None, mds: bool = False) -> dict[str, Any]:
    """Builds one render_meta section entry, regular or multi-data."""
    entry: dict[str, Any] = {
        'type': 'multi-data-section' if mds else 'section',
        'name': name,
        'fields': fields,
    }

    if label is not None:
        entry['label'] = label

    return entry


def _type(fields: list[dict[str, Any]], sections: list[dict[str, Any]], label: str = 'Router') -> CmdbType:
    """Builds a CmdbType from the given fields and render_meta sections."""
    return CmdbType.from_data({
        'public_id': 1,
        'name': 'router',
        'label': label,
        'author_id': 1,
        'active': True,
        'fields': fields,
        'render_meta': {'icon': 'fa-cube', 'sections': sections, 'summary': {'fields': []}},
        'acl': {'activated': False},
    })


def _plain_type() -> CmdbType:
    """A type with one labelled regular field, one unlabelled one and a two-field MDS section."""
    return _type(
        [
            _field('hostname', 'Hostname'),
            _field('notes'),
            _field('port', 'Port'),
            _field('speed', 'Speed'),
        ],
        [
            _section(REGULAR_SECTION, ['hostname', 'notes'], 'Main'),
            _section(MDS_SECTION, ['port', 'speed'], MDS_SECTION_LABEL, mds=True),
        ],
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_template_column                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_regular_column_is_label_plus_bracketed_name() -> None:
    """A regular field reads `<Label> [<name>]` - no MDS part."""
    assert build_template_column('Hostname', 'hostname') == 'Hostname [hostname]'


def test_an_mds_column_names_its_section_between_label_and_name() -> None:
    """An MDS field reads `<Label> [MDS-<Section>] [<name>]`, so two MDS sections stay apart."""
    assert build_template_column('Port', 'port', MDS_SECTION_LABEL) == 'Port [MDS-Network Interfaces] [port]'


def test_an_empty_mds_section_label_leaves_the_column_regular() -> None:
    """No section label means no MDS part rather than an empty marker."""
    assert build_template_column('Port', 'port', '') == 'Port [port]'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_field_label_map                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_field_label_map_falls_back_to_the_field_name() -> None:
    """A field without a label (or with an empty one) is headed by its own name."""
    type_instance = _type(
        [_field('hostname', 'Hostname'), _field('notes'), _field('blank', '')],
        [_section(REGULAR_SECTION, ['hostname', 'notes', 'blank'])],
    )

    assert build_field_label_map(type_instance) == {
        'hostname': 'Hostname', 'notes': 'notes', 'blank': 'blank',
    }


def test_field_label_map_skips_a_field_without_a_name() -> None:
    """A nameless field entry cannot be a column and is ignored instead of raising."""
    type_instance = _type([_field('hostname', 'Hostname'), {'type': 'text'}], [])

    assert build_field_label_map(type_instance) == {'hostname': 'Hostname'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             collect_template_field_layout                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_layout_splits_regular_fields_from_the_mds_sections() -> None:
    """Regular fields come back flat, MDS fields grouped under their section label."""
    regular_fields, mds_layout = collect_template_field_layout(_plain_type())

    assert regular_fields == ['hostname', 'notes']
    assert mds_layout == [(MDS_SECTION_LABEL, ['port', 'speed'])]


def test_layout_follows_the_declared_section_order() -> None:
    """Sections are walked top-to-bottom, so the template follows the layout shown in the UI."""
    type_instance = _type(
        [_field('a'), _field('b'), _field('c')],
        [_section('second', ['b']), _section('first', ['c', 'a'])],
    )

    regular_fields, _ = collect_template_field_layout(type_instance)

    assert regular_fields == ['b', 'c', 'a']


def test_layout_falls_back_to_the_section_name_without_a_label() -> None:
    """A multi-data-section without a label is named by its own name (TypeSection titles it)."""
    type_instance = _type([_field('port', 'Port')], [_section('ifaces', ['port'], mds=True)])

    _, mds_layout = collect_template_field_layout(type_instance)

    assert mds_layout == [('Ifaces', ['port'])]


def test_layout_appends_a_field_no_section_places() -> None:
    """A field the type declares but no section shows is still given a column, at the end."""
    type_instance = _type(
        [_field('hostname', 'Hostname'), _field('orphan', 'Orphan')],
        [_section(REGULAR_SECTION, ['hostname'])],
    )

    regular_fields, _ = collect_template_field_layout(type_instance)

    assert regular_fields == ['hostname', 'orphan']


def test_layout_emits_a_field_placed_twice_only_once() -> None:
    """A malformed type listing one field in two sections must not produce a duplicate column."""
    type_instance = _type(
        [_field('port', 'Port')],
        [_section(REGULAR_SECTION, ['port']), _section(MDS_SECTION, ['port'], MDS_SECTION_LABEL, mds=True)],
    )

    regular_fields, mds_layout = collect_template_field_layout(type_instance)

    assert regular_fields == ['port']
    assert mds_layout == [(MDS_SECTION_LABEL, [])]


def test_layout_ignores_a_blank_field_name_in_a_section() -> None:
    """A section referencing an empty field name contributes no column."""
    type_instance = _type([_field('hostname', 'Hostname')], [_section(REGULAR_SECTION, ['', 'hostname'])])

    regular_fields, _ = collect_template_field_layout(type_instance)

    assert regular_fields == ['hostname']


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_object_template_header                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_header_mirrors_an_export_identity_then_regular_then_mds() -> None:
    """The full header: identity columns, regular fields in section order, then the MDS fields."""
    assert build_object_template_header(_plain_type()) == [
        *IDENTITY_COLUMNS,
        'Hostname [hostname]',
        'notes [notes]',
        'Port [MDS-Network Interfaces] [port]',
        'Speed [MDS-Network Interfaces] [speed]',
    ]


def test_header_leads_with_the_two_identity_columns() -> None:
    """public_id and active head the file, in that order, whatever the type declares."""
    assert build_object_template_header(_plain_type())[:2] == IDENTITY_COLUMNS


def test_header_groups_each_mds_section_separately() -> None:
    """Two multi-data-sections keep their own marker, so their columns are never confused."""
    type_instance = _type(
        [_field('port', 'Port'), _field('disk', 'Disk')],
        [
            _section('ifaces', ['port'], 'Interfaces', mds=True),
            _section('disks', ['disk'], 'Disks', mds=True),
        ],
    )

    assert build_object_template_header(type_instance)[2:] == [
        'Port [MDS-Interfaces] [port]',
        'Disk [MDS-Disks] [disk]',
    ]


def test_header_includes_reference_and_location_fields() -> None:
    """Field types whose values the import clears still get a column - the shape stays complete."""
    type_instance = _type(
        [
            _field('owner', 'Owner', 'ref'),
            _field('site', 'Site', 'location'),
            _field('linked', 'Linked', 'ref-section-field'),
        ],
        [_section(REGULAR_SECTION, ['owner', 'site', 'linked'])],
    )

    assert build_object_template_header(type_instance)[2:] == [
        'Owner [owner]', 'Site [site]', 'Linked [linked]',
    ]


def test_header_has_no_duplicate_columns() -> None:
    """Every column of a template is unique, so a filled-in file maps unambiguously."""
    header = build_object_template_header(_plain_type())

    assert len(header) == len(set(header))


# -------------------------------------------------------------------------------------------------------------------- #
#                                               type_has_template_fields                                               #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('fields,expected', [
    ([_field('hostname', 'Hostname')], True),
    ([], False),
    ([{'type': 'text'}], False),
])
def test_type_has_template_fields(fields: list[dict[str, Any]], expected: bool) -> None:
    """A type is templatable only when it declares at least one usable (named) field."""
    assert type_has_template_fields(_type(fields, [])) is expected

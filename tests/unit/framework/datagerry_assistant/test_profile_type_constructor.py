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
Unit tests for cmdb.framework.datagerry_assistant.profile_type_constructor

Exercises the public builder surface (create_type_config, create_special_type_config,
add_conditional_sections, create_conditional_ref_section). The private helpers are covered
through these. The non-deterministic ci_explorer_color and creation_time are asserted
structurally (shape/type) rather than by exact value.
"""
import re
from typing import Any
from datetime import datetime

from cmdb.models.type_model import FieldType, TypeSchemaKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import (
    RenderMetaKey,
)
from cmdb.framework.datagerry_assistant.profile_type_constructor import ProfileTypeConstructor

# Input dicts use the same plain-string keys the profiles use; the builder reads them via enums
_INFO_SECTION: dict[str, Any] = {
    'name': 'sec-info',
    'label': 'Information',
    'fields': [
        {'type': 'text', 'name': 'text-name', 'label': 'Name', 'is_summary': True},
        {'type': 'text', 'name': 'text-note', 'label': 'Note'},
    ],
}
# -------------------------------------------------------------------------------------------------------------------- #
#                                                create_type_config                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_create_type_config_sets_skeleton_and_defaults(type_constructor: ProfileTypeConstructor) -> None:
    """The type body carries the given identity plus the fixed defaults (active/version/author)"""
    cfg: dict[str, Any] = type_constructor.create_type_config([_INFO_SECTION], 'demo', 'Demo', 'fas fa-cube')

    assert cfg[TypeSchemaKey.NAME] == 'demo'
    assert cfg[TypeSchemaKey.LABEL] == 'Demo'
    assert cfg[TypeSchemaKey.ACTIVE] is True
    assert cfg[TypeSchemaKey.SELECTABLE_AS_PARENT] is True
    assert cfg[TypeSchemaKey.VERSION] == '1.0.0'
    assert cfg[TypeSchemaKey.AUTHOR_ID] == 1
    assert cfg[TypeSchemaKey.GLOBAL_TEMPLATE_IDS] == []
    assert cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.ICON] == 'fas fa-cube'


def test_create_type_config_non_deterministic_fields_have_valid_shape(
    type_constructor: ProfileTypeConstructor,
) -> None:
    """ci_explorer_color is a 6-digit hex color and creation_time is a datetime"""
    cfg: dict[str, Any] = type_constructor.create_type_config([_INFO_SECTION], 'demo', 'Demo', 'fas fa-cube')

    assert re.fullmatch(r'#[0-9A-F]{6}', cfg[TypeSchemaKey.CI_EXPLORER_COLOR])
    assert isinstance(cfg[TypeSchemaKey.CREATION_TIME], datetime)


def test_create_type_config_builds_sections_fields_and_summary(type_constructor: ProfileTypeConstructor) -> None:
    """Fields land in the flat list, under their section by name, and is_summary fields in summary"""
    cfg: dict[str, Any] = type_constructor.create_type_config([_INFO_SECTION], 'demo', 'Demo', 'fas fa-cube')

    sections: list[dict[str, Any]] = cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS]
    assert [section['name'] for section in sections] == ['sec-info']
    assert sections[0]['fields'] == ['text-name', 'text-note']

    assert [field['name'] for field in cfg[TypeSchemaKey.FIELDS]] == ['text-name', 'text-note']
    assert cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SUMMARY][RenderMetaKey.FIELDS] == ['text-name']


def test_create_type_config_lifts_only_accepted_extras(type_constructor: ProfileTypeConstructor) -> None:
    """Accepted extra keys are copied onto the field; unknown extras are dropped"""
    section: dict[str, Any] = {
        'name': 'sec-x',
        'label': 'X',
        'fields': [{
            'type': 'select',
            'name': 'sel-1',
            'label': 'Type',
            'extras': {'options': [{'name': 'a', 'label': 'A'}], 'regex': '^x$', 'unknown_key': 'nope'},
        }],
    }

    cfg: dict[str, Any] = type_constructor.create_type_config([section], 'demo', 'Demo', 'fas fa-cube')
    field: dict[str, Any] = cfg[TypeSchemaKey.FIELDS][0]

    assert field['options'] == [{'name': 'a', 'label': 'A'}]
    assert field['regex'] == '^x$'
    assert 'unknown_key' not in field


def test_create_type_config_inlines_predefined_template(type_constructor: ProfileTypeConstructor) -> None:
    """A predefined template section records its name in global_template_ids and inlines its fields"""
    template_section: dict[str, Any] = type_constructor.get_predefined_template_data('dg-modelspec')

    cfg: dict[str, Any] = type_constructor.create_type_config(
        [_INFO_SECTION, template_section], 'demo', 'Demo', 'fas fa-cube',
    )

    assert cfg[TypeSchemaKey.GLOBAL_TEMPLATE_IDS] == ['dg-modelspec']
    section_names: list[str] = [section['name'] for section in cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS]]
    assert 'dg-modelspec' in section_names
    flat_names: list[str] = [field['name'] for field in cfg[TypeSchemaKey.FIELDS]]
    assert 'dg-modelspec-model' in flat_names


def test_create_type_config_preserves_mds_section_type(type_constructor: ProfileTypeConstructor) -> None:
    """A section declared as a multi-data-section keeps its type and gains an empty hidden_fields list"""
    mds_section: dict[str, Any] = {
        'type': SectionType.MDS_SECTION,
        'name': 'sec-mds',
        'label': 'MDS',
        'fields': [{'type': 'text', 'name': 'f1', 'label': 'F1'}],
    }

    cfg: dict[str, Any] = type_constructor.create_type_config([mds_section], 'demo', 'Demo', 'fas fa-cube')
    section: dict[str, Any] = next(
        s for s in cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS] if s['name'] == 'sec-mds'
    )

    assert section['type'] == SectionType.MDS_SECTION
    assert section['hidden_fields'] == []


def test_create_type_config_plain_section_stays_plain(type_constructor: ProfileTypeConstructor) -> None:
    """A section without an explicit type defaults to a plain section and carries no hidden_fields"""
    cfg: dict[str, Any] = type_constructor.create_type_config([_INFO_SECTION], 'demo', 'Demo', 'fas fa-cube')
    section: dict[str, Any] = cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS][0]

    assert section['type'] == SectionType.SECTION
    assert 'hidden_fields' not in section


def test_get_ipam_interface_template_data_wires_subnet_ref(type_constructor: ProfileTypeConstructor) -> None:
    """A given Subnet type id is set on the interface template's Subnet reference field"""
    template: dict[str, Any] = type_constructor.get_ipam_interface_template_data(42)

    assert template['type'] == SectionType.MDS_SECTION
    subnet_field: dict[str, Any] = next(f for f in template['fields'] if f['name'] == InterfaceField.SUBNET)
    assert subnet_field['extras']['ref_types'] == [42]
    assert template['global_id_name'] == IpamSection.INTERFACE


def test_get_ipam_interface_template_data_leaves_ref_empty_without_subnet(
    type_constructor: ProfileTypeConstructor,
) -> None:
    """With no Subnet type (None) the interface template's Subnet reference stays empty"""
    template: dict[str, Any] = type_constructor.get_ipam_interface_template_data(None)

    subnet_field: dict[str, Any] = next(f for f in template['fields'] if f['name'] == InterfaceField.SUBNET)
    assert subnet_field['extras']['ref_types'] == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                            create_special_type_config                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def _blueprint() -> dict[str, Any]:
    """A minimal SpecialType blueprint shaped like SchemaProvider output"""
    return {
        TypeSchemaKey.SPECIAL_TYPE: 'SUPERNET',
        TypeSchemaKey.SECTIONS: [
            {'type': 'section', 'name': 'dg-information', 'label': 'Information', 'fields': ['dg-name']},
        ],
        TypeSchemaKey.FIELDS: [
            {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
            {'type': 'text', 'name': 'dg-network-range', 'label': 'Network Range'},
        ],
    }


def test_create_special_type_config_sets_marker_sections_and_fields(
    type_constructor: ProfileTypeConstructor,
) -> None:
    """The blueprint's special_type / sections / fields are placed verbatim into the type config"""
    blueprint: dict[str, Any] = _blueprint()

    cfg: dict[str, Any] = type_constructor.create_special_type_config(blueprint, 'supernet', 'Supernet', 'fas fa-x')

    assert cfg[TypeSchemaKey.SPECIAL_TYPE] == 'SUPERNET'
    assert cfg[TypeSchemaKey.NAME] == 'supernet'
    assert cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS] == blueprint[TypeSchemaKey.SECTIONS]
    assert cfg[TypeSchemaKey.FIELDS] == blueprint[TypeSchemaKey.FIELDS]


def test_create_special_type_config_marks_first_field_as_summary(
    type_constructor: ProfileTypeConstructor,
) -> None:
    """The SpecialType's name field (first field) becomes the summary field"""
    cfg: dict[str, Any] = type_constructor.create_special_type_config(_blueprint(), 'supernet', 'Supernet', 'fas fa-x')

    assert cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SUMMARY][RenderMetaKey.FIELDS] == ['dg-name']

# -------------------------------------------------------------------------------------------------------------------- #
#                                  conditional sections (the bug-adjacent logic)                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_add_conditional_sections_includes_section_when_all_ids_present(
    type_constructor: ProfileTypeConstructor,
) -> None:
    """A conditional section is appended and its ref field wired when every id is set"""
    type_constructor.create_type_config([_INFO_SECTION], 'demo', 'Demo', 'fas fa-cube')
    section = type_constructor.create_conditional_ref_section('ref-os', 'OS', 'sec-os', 'Operating system', [7])

    type_constructor.add_conditional_sections([section])

    cfg: dict[str, Any] = type_constructor.type_config
    sections: list[dict[str, Any]] = cfg[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS]
    assert 'sec-os' in [s['name'] for s in sections]
    ref_field: dict[str, Any] = next(f for f in cfg[TypeSchemaKey.FIELDS] if f['name'] == 'ref-os')
    assert ref_field['type'] == FieldType.REFERENCE
    assert ref_field['ref_types'] == [7]


def test_add_conditional_sections_skips_section_when_any_id_is_none(
    type_constructor: ProfileTypeConstructor,
) -> None:
    """A conditional section whose ids contain None is not added"""
    type_constructor.create_type_config([_INFO_SECTION], 'demo', 'Demo', 'fas fa-cube')
    ok = type_constructor.create_conditional_ref_section('ref-os', 'OS', 'sec-os', 'Operating system', [7])
    skip = type_constructor.create_conditional_ref_section('ref-user', 'User', 'sec-user', 'User', [None])

    type_constructor.add_conditional_sections([ok, skip])

    sections: list[dict[str, Any]] = type_constructor.type_config[TypeSchemaKey.RENDER_META][RenderMetaKey.SECTIONS]
    names: list[str] = [s['name'] for s in sections]
    assert 'sec-os' in names
    assert 'sec-user' not in names


def test_create_conditional_ref_section_shape(type_constructor: ProfileTypeConstructor) -> None:
    """The factory returns a section carrying its conditional ids and one empty-ref ref-field"""
    section: dict[str, Any] = type_constructor.create_conditional_ref_section(
        'ref-os', 'OS', 'sec-os', 'Operating system', [1, 2],
    )

    assert section['conditional_ids'] == [1, 2]
    assert section['name'] == 'sec-os'
    ref_field: dict[str, Any] = section['fields'][0]
    assert ref_field['type'] == FieldType.REFERENCE
    assert ref_field['extras']['ref_types'] == []

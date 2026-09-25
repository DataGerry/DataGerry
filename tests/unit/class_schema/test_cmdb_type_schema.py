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
Unit tests for the section rules of cmdb.class_schema.type_model.cmdb_type_schema

A section's kind decides how the whole stack treats it: which class builds it, whether its fields are
multi-data fields, whether a client draws a table or a form. The schema is the only place a write can
be stopped before that kind is stored, and the type IMPORT refuses an unknown one as well. These tests
pin the two doors to the same answer.
"""
import pytest
from cerberus import Validator

from cmdb.class_schema.type_model.cmdb_type_schema import get_cmdb_type_schema
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.section_key_enum import SectionKey
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_NAME: str = 'schema-test-type'
FIELD_NAME: str = 'dg-name'


def _type_payload(section_kind: str) -> dict:
    """A minimal CmdbType payload whose single section declares the given kind."""
    return {
        'name': TYPE_NAME,
        'label': 'Schema Test',
        'author_id': 1,
        'active': True,
        'fields': [{'type': 'text', 'name': FIELD_NAME, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{
                SectionKey.TYPE.value: section_kind,
                SectionKey.NAME.value: 'main',
                SectionKey.LABEL.value: 'Main',
                SectionKey.FIELDS.value: [FIELD_NAME],
            }],
            'summary': {'fields': [FIELD_NAME]},
        },
        'version': '1.0.0',
    }


def _validate(section_kind: str) -> bool:
    """Validates a payload carrying the given section kind the way the write routes do."""
    return Validator(get_cmdb_type_schema(), purge_unknown=True).validate(_type_payload(section_kind))


@pytest.mark.parametrize('section_kind', [member.value for member in SectionType])
def test_every_known_section_kind_is_accepted(section_kind: str) -> None:
    """Each SectionType member passes - the rule is derived from the enum, so it cannot drift."""
    assert _validate(section_kind) is True


@pytest.mark.parametrize('section_kind', ['multi-data-sections', 'refsection', '', 'SECTION'])
def test_a_section_kind_outside_the_enum_is_refused(section_kind: str) -> None:
    """
    A kind the enum does not name is refused, typo or not

    The near-misses are the reason: a stored 'multi-data-sections' is read back as a PLAIN section
    (`TypeRenderMeta.SECTION_CLASSES` falls back for a kind it does not know), so its fields quietly
    stop being multi-data fields and Objects of the Type store no rows for it.
    """
    assert _validate(section_kind) is False


def test_the_allowed_kinds_are_the_enum_members() -> None:
    """The schema states the rule by deriving it, so a new SectionType member needs no schema edit."""
    section_schema = get_cmdb_type_schema()['render_meta']['schema']['sections']['schema']['schema']

    assert section_schema[SectionKey.TYPE.value]['allowed'] == [member.value for member in SectionType]

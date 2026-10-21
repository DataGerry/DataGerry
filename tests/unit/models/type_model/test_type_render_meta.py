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
Unit tests for TypeRenderMeta

The `render_meta` half of a stored CmdbType: the icon, the summary and the section list the frontend
draws the object view from. `from_data` dispatches each stored section onto its section class by the
section's `type` key.

The uncovered branch was the fall-through: a section whose `type` is none of the three known values
is built as a plain field section rather than refused. That matters for a type saved by a newer
version and read by an older one, and for a document where the key is absent entirely.
"""
from typing import Any

import pytest

from cmdb.models.type_model.type_render_meta import TypeRenderMeta
from cmdb.models.type_model.type_field_section import TypeFieldSection
from cmdb.models.type_model.type_multi_data_section import TypeMultiDataSection
from cmdb.models.type_model.type_reference_section import TypeReferenceSection
# -------------------------------------------------------------------------------------------------------------------- #

SECTION_NAME: str = 'dg-section-1'
SECTION_LABEL: str = 'Section 1'


def _section(section_type: str | None, name: str = SECTION_NAME) -> dict[str, Any]:
    """A stored section document; `None` omits the type key entirely."""
    section: dict[str, Any] = {'name': name, 'label': SECTION_LABEL, 'fields': []}

    if section_type is not None:
        section['type'] = section_type

    return section


def _meta(*sections: dict[str, Any]) -> TypeRenderMeta:
    """Builds a TypeRenderMeta from the given stored sections."""
    return TypeRenderMeta.from_data({'sections': list(sections)})


class TestSectionDispatch:
    """Each stored section becomes the class its `type` names."""

    @pytest.mark.parametrize('section_type, expected', [
        ('section', TypeFieldSection),
        ('multi-data-section', TypeMultiDataSection),
        ('ref-section', TypeReferenceSection),
    ], ids=str)
    def test_a_known_type_builds_its_own_class(self, section_type: str, expected: type) -> None:
        """Getting this wrong changes what the object view renders for the whole section."""
        meta = _meta(_section(section_type))

        assert isinstance(meta.sections[0], expected)

    def test_an_absent_type_key_defaults_to_a_field_section(self) -> None:
        """The `.get('type', 'section')` default - a section document written before the key existed."""
        meta = _meta(_section(None))

        assert isinstance(meta.sections[0], TypeFieldSection)

    def test_an_unknown_type_falls_back_to_a_field_section(self) -> None:
        """
        A section type this version does not know is rendered as a plain one, not dropped

        The alternative - refusing the document - would make a type saved by a newer version
        unreadable here, and dropping the section would silently lose its fields. Note the fall-back
        is byte-identical to the `'section'` branch above it.
        """
        meta = _meta(_section('dg-section-type-from-the-future'))

        assert isinstance(meta.sections[0], TypeFieldSection)

    def test_every_section_is_kept_in_order(self) -> None:
        """Section order is the order the frontend draws them in."""
        meta = _meta(
            _section('section', 'first'),
            _section('unknown-type', 'second'),
            _section('multi-data-section', 'third'),
        )

        assert [section.name for section in meta.sections] == ['first', 'second', 'third']


class TestTheRestOfTheMeta:
    """The two scalar members beside the section list."""

    def test_no_sections_is_valid(self) -> None:
        """A type with no sections yet is a normal intermediate state in the type builder."""
        assert TypeRenderMeta.from_data({}).sections == []

    def test_the_icon_is_carried_through(self) -> None:
        """The icon is what the frontend draws beside the type everywhere it lists one."""
        assert TypeRenderMeta.from_data({'icon': 'fa-server'}).icon == 'fa-server'

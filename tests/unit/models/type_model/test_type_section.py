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
Unit tests for TypeSection

The base of the three section classes a CmdbType's `render_meta` is built from - `TypeFieldSection`,
`TypeMultiDataSection` and `TypeReferenceSection` all extend it and all inherit its three members.
`TypeRenderMeta.from_data` dispatches a stored section onto one of them by its `type` key.

Its own `from_data` / `to_json` had no coverage because the subclasses override both. What is
exercised here is the base contract they build on, and the label default in particular: a section
stored without a label is titled from its name rather than rendered blank.
"""
import pytest

from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

SECTION_NAME: str = 'dg-network-details'
SECTION_LABEL: str = 'Network Details'


def _stored(**overrides) -> dict:
    """A stored section document."""
    return {'type': SectionType.SECTION.value, 'name': SECTION_NAME, 'label': SECTION_LABEL, **overrides}


class TestFromData:
    """Building a section from its stored document."""

    def test_reads_every_member(self) -> None:
        """All three are frontend-visible: the type picks the renderer, the label is the heading."""
        section = TypeSection.from_data(_stored())

        assert section.type == SectionType.SECTION.value
        assert section.name == SECTION_NAME
        assert section.label == SECTION_LABEL

    def test_a_missing_label_is_titled_from_the_name(self) -> None:
        """
        A section saved without a label still renders a heading

        `name` is the immutable identifier and is never blank, so titling it is always better than
        an empty heading - which is what the frontend would draw for None.
        """
        section = TypeSection.from_data({'type': SectionType.SECTION.value, 'name': 'network_details'})

        assert section.label == 'Network_Details'

    def test_an_empty_label_is_titled_from_the_name(self) -> None:
        """An empty string is the shape a cleared form field stores, and means the same as absent."""
        section = TypeSection.from_data(_stored(label=''))

        assert section.label == SECTION_NAME.title()

    @pytest.mark.parametrize('missing', ['type', 'name'], ids=str)
    def test_the_identifying_keys_are_required(self, missing: str) -> None:
        """
        Both are read with a bare subscript, so a document without them raises rather than defaulting

        A section with no `name` could not be addressed at all, and one with no `type` could not be
        dispatched onto a renderer - neither has a sensible default.
        """
        document = _stored()
        del document[missing]

        with pytest.raises(KeyError):
            TypeSection.from_data(document)


class TestToJson:
    """What goes back into the stored CmdbType."""

    def test_emits_the_three_members(self) -> None:
        """The section's whole persisted shape at this level; subclasses add their own keys."""
        assert TypeSection.to_json(TypeSection.from_data(_stored())) == {
            'type': SectionType.SECTION.value,
            'name': SECTION_NAME,
            'label': SECTION_LABEL,
        }

    def test_round_trips(self) -> None:
        """What was written has to read back as the same section."""
        original = TypeSection.from_data(_stored())
        restored = TypeSection.from_data(TypeSection.to_json(original))

        assert (restored.type, restored.name, restored.label) == (original.type, original.name, original.label)

    def test_the_derived_label_is_persisted(self) -> None:
        """The default is resolved once on read, so a later save stores it rather than re-deriving."""
        section = TypeSection.from_data({'type': SectionType.SECTION.value, 'name': SECTION_NAME})

        assert TypeSection.to_json(section)['label'] == SECTION_NAME.title()

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
Unit tests for cmdb.models.type_model.type_reference

What a reference field shows. The class had **no test module of its own** until 2026-09-10 - the only
test that touched it patched one of its methods to raise, through the renderer - and half of it was
dead: `from_data`, `has_prefix`, `has_icon` and `has_summaries` had no caller anywhere in the
repository (the `has_summaries` call sites in the codebase are `CmdbType`'s), which is exactly why the
file sat at 83%. Those four are gone; what is left is a value object with one serialiser, the empty
sentinel and the two summary-line helpers.

Pinned here, because all three are contract rather than implementation:

* **the seven-key payload** `TypeReferenceKey` names - the Angular reference field reads every one of
  them (`ref.component.html`), and the human-readable exporter reads three;
* **`object_id` 0 as the empty reference** - what the frontend hides the block on, and what the
  renderer answers for a field with no value or an unresolvable object;
* **the line helpers**: a line without placeholders needs no filling, a line that is absent, empty or
  not text at all needs nothing either (the check used to raise for None and the renderer worked
  around it), and a line that does not fit its values is reported rather than half-filled.

Pure tests: no Mongo, no Flask.
"""
from typing import Any

import pytest

from cmdb.models.type_model.type_reference import (
    EMPTY_REFERENCE_OBJECT_ID,
    EMPTY_REFERENCE_TYPE_ID,
    TypeReference,
)
from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey

from cmdb.errors.models.cmdb_type import CmdbTypeReferenceLineFillError
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 701
OBJECT_ID: int = 4711
TYPE_LABEL: str = 'Server'
ICON: str = 'fas fa-server'
SUMMARIES: list[dict[str, Any]] = [{'name': 'hostname', 'value': 'srv-01', 'type': 'text'}]


def _reference(**overrides: Any) -> TypeReference:
    """A resolved TypeReference, as the renderer builds one."""
    values: dict[str, Any] = {
        'type_id': TYPE_ID,
        'object_id': OBJECT_ID,
        'type_label': TYPE_LABEL,
        'line': 'Host srv-01',
        'prefix': False,
        'icon': ICON,
        'summaries': SUMMARIES,
    }
    values.update(overrides)

    return TypeReference(**values)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the constructor                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """The place the optional payload values are normalised."""

    def test_the_values_are_stored_as_given(self) -> None:
        """Nothing is invented and nothing is dropped"""
        reference = _reference()

        assert reference.type_id == TYPE_ID
        assert reference.object_id == OBJECT_ID
        assert reference.type_label == TYPE_LABEL
        assert reference.line == 'Host srv-01'
        assert reference.icon == ICON
        assert reference.summaries == SUMMARIES
        assert reference.prefix is False

    def test_a_missing_label_becomes_an_empty_label(self) -> None:
        """The frontend prints the label next to the id, so a null would show as 'null'"""
        assert _reference(type_label=None).type_label == ''

    def test_a_missing_summary_list_becomes_an_empty_list(self) -> None:
        """The frontend iterates it, and the exporter reads it with a default of []"""
        assert _reference(summaries=None).summaries == []

    @pytest.mark.parametrize('prefix, expected', [
        (True, True), (False, False), (None, False), ('', False), ('yes', True), (1, True),
    ])
    def test_the_prefix_flag_is_coerced_to_a_boolean(self, prefix: Any, expected: bool) -> None:
        """It reaches the payload as a two-state flag whatever the summary configuration answered"""
        assert _reference(prefix=prefix).prefix is expected

    def test_a_line_may_be_absent(self) -> None:
        """
        A type configuring no summary line is the normal case

        The frontend then shows icon + label + #id + the summary fields instead.
        """
        assert _reference(line=None).line is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                the empty reference                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEmpty:
    """The sentinel the renderer answers when nothing resolves."""

    def test_its_ids_are_zero(self) -> None:
        """`object_id` 0 is what the Angular reference field hides the whole block on"""
        empty = TypeReference.empty()

        assert empty.type_id == EMPTY_REFERENCE_TYPE_ID
        assert empty.object_id == EMPTY_REFERENCE_OBJECT_ID
        assert EMPTY_REFERENCE_OBJECT_ID == 0

    def test_it_carries_no_label_and_no_line(self) -> None:
        """An unresolved reference has nothing to say about the object it points at"""
        empty = TypeReference.empty()

        assert empty.type_label == ''
        assert empty.line == ''
        assert empty.summaries == []

    def test_it_serialises_to_the_full_payload(self) -> None:
        """
        The empty reference is a complete payload, not a partial one

        Both the frontend and the exporter read INTO the dict, so every key has to be there.
        """
        assert set(TypeReference.to_json(TypeReference.empty())) == {key.value for key in TypeReferenceKey}

    def test_each_call_answers_a_fresh_reference(self) -> None:
        """The renderer mutates the one it gets, so a shared instance would leak between fields"""
        first = TypeReference.empty()
        first.object_id = OBJECT_ID

        assert TypeReference.empty().object_id == EMPTY_REFERENCE_OBJECT_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      to_json                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestToJson:
    """The payload three consumers read."""

    def test_it_emits_exactly_the_key_enum(self) -> None:
        """A key added to the payload without the enum is a key no consumer knows to read"""
        assert list(TypeReference.to_json(_reference())) == [key.value for key in TypeReferenceKey]

    def test_the_values_are_the_instance_values(self) -> None:
        """The seven keys the Angular reference field reads, in one assertion"""
        assert TypeReference.to_json(_reference()) == {
            TypeReferenceKey.TYPE_ID.value: TYPE_ID,
            TypeReferenceKey.OBJECT_ID.value: OBJECT_ID,
            TypeReferenceKey.LINE.value: 'Host srv-01',
            TypeReferenceKey.TYPE_LABEL.value: TYPE_LABEL,
            TypeReferenceKey.SUMMARIES.value: SUMMARIES,
            TypeReferenceKey.ICON.value: ICON,
            TypeReferenceKey.PREFIX.value: False,
        }

    def test_an_unresolved_reference_answers_nulls_rather_than_missing_keys(self) -> None:
        """A type without an icon is a null icon, not an absent one"""
        payload = TypeReference.to_json(_reference(icon=None, line=None))

        assert payload[TypeReferenceKey.ICON.value] is None
        assert payload[TypeReferenceKey.LINE.value] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the line helpers                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLineRequiresFields:
    """Whether the summary line has placeholders to fill."""

    @pytest.mark.parametrize('line', ['Name {}', '{} in {}', 'prefix {0} suffix', '{name}'])
    def test_a_line_with_placeholders_requires_fields(self, line: str) -> None:
        """These are the lines whose summary values have to be formatted in"""
        assert _reference(line=line).line_requires_fields() is True

    @pytest.mark.parametrize('line', ['Static name', '', 'no braces at all', '{'])
    def test_a_line_without_a_complete_placeholder_requires_none(self, line: str) -> None:
        """A stray opening brace is not a placeholder - and is what makes fill_line refuse later"""
        assert _reference(line=line).line_requires_fields() is False

    @pytest.mark.parametrize('line', [None, 7, ['{}']])
    def test_an_absent_or_non_text_line_requires_nothing(self, line: Any) -> None:
        """
        Answered rather than raised

        The regex used to be handed `self.line` unchecked, so a None line - the default - raised a
        TypeError. The renderer guarded the CALL instead, with a comment about the DEBUG logs it
        otherwise spammed.
        """
        assert _reference(line=line).line_requires_fields() is False


class TestFillLine:
    """Formatting the referenced object's summary values into the line."""

    def test_the_values_are_formatted_in(self) -> None:
        """The filled line is what the frontend shows instead of the label and the fields"""
        reference = _reference(line='{} in {}')

        reference.fill_line(['srv-01', 'Rack 4'])

        assert reference.line == 'srv-01 in Rack 4'

    def test_a_line_without_placeholders_is_unchanged(self) -> None:
        """A static line is answered as configured, extra values and all"""
        reference = _reference(line='Static')

        reference.fill_line(['unused'])

        assert reference.line == 'Static'

    def test_too_few_values_are_refused(self) -> None:
        """The type's summary fields changed after the line was written - the usual cause"""
        with pytest.raises(CmdbTypeReferenceLineFillError):
            _reference(line='{} in {}').fill_line(['srv-01'])

    def test_a_stray_brace_is_refused(self) -> None:
        """`str.format` raises for it, and the message has to name the line it happened on"""
        with pytest.raises(CmdbTypeReferenceLineFillError) as err:
            _reference(line='Name {').fill_line([])

        assert 'Name {' in str(err.value)

    def test_a_refused_line_is_left_unfilled(self) -> None:
        """
        The template survives the failure, which is why the caller has to decide what to answer

        The renderer clears it and reports; answering it would show the raw '{}' to a user.
        """
        reference = _reference(line='{} in {}')

        with pytest.raises(CmdbTypeReferenceLineFillError):
            reference.fill_line(['srv-01'])

        assert reference.line == '{} in {}'

    def test_a_non_text_line_is_refused(self) -> None:
        """The one path that does not check the line's type first reports instead of raising a TypeError"""
        with pytest.raises(CmdbTypeReferenceLineFillError):
            _reference(line=None).fill_line([])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the retired surface                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRetiredMembers:
    """Four members had no caller anywhere and were removed on 2026-09-10."""

    @pytest.mark.parametrize('member', ['from_data', 'has_prefix', 'has_icon', 'has_summaries'])
    def test_they_are_gone(self, member: str) -> None:
        """
        Asserted so a future caller writes what it needs instead of resurrecting a dead default

        `from_data` in particular disagreed with the constructor about two defaults (icon False vs
        None, prefix None vs False), and `has_summaries` reads like `CmdbType.has_summaries` - the
        one that IS called.
        """
        assert not hasattr(TypeReference, member)

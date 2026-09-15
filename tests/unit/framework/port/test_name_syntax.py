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
Unit tests for cmdb.framework.port.name_syntax

The pure half of the creation assistant, and the place a mistake is cheapest to catch: a syntax that
renders wrongly produces 48 wrong port names in one click, and a unique index that refuses the 13th of
them leaves a half-created device behind.

Every rule the concept states is exercised here - the four tokens, the padding, the start index, an
unknown token, an empty syntax, a syntax duplicating within its own batch, and collisions against ports
that already exist.

Pure tests: no Mongo, no Flask, no fixtures
"""
from typing import Any

import pytest

from cmdb.framework.port.name_syntax import (
    colliding_names,
    duplicate_names,
    find_tokens,
    generate_names,
    is_known_token,
    parse_pad_width,
    render_name,
    syntax_blockers,
)
from cmdb.framework.port.name_syntax_constants import MAX_PAD_WIDTH, PortNameSyntaxError, SyntaxToken
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  reading a syntax                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFindTokens:
    """Every {...} is a token, whether or not it is one we know."""

    def test_the_tokens_are_found_in_order(self) -> None:
        """The order matters for nothing but the message, and it should still read naturally"""
        assert find_tokens('{prefix}-{slot}/{n:02}') == ['prefix', 'slot', 'n:02']

    def test_a_syntax_without_tokens_has_none(self) -> None:
        """Legal on its own - a single fixed name - and caught by the duplicate check in a batch"""
        assert find_tokens('uplink') == []

    def test_an_unknown_token_is_still_found(self) -> None:
        """
        It has to be recognised as a token before it can be refused BY NAME

        A pattern matching only the valid tokens would let '{slt}' through as literal text, and the
        customer would get 48 ports with a brace in their name.
        """
        assert find_tokens('Gi0/{slt}') == ['slt']


class TestParsePadWidth:
    """{n} is the counter; {n:02} is the counter zero-padded."""

    def test_the_bare_counter_pads_to_nothing(self) -> None:
        """Width 0, not None - it IS a numbering token"""
        assert parse_pad_width('n') == 0

    @pytest.mark.parametrize('token,width', [('n:01', 1), ('n:02', 2), ('n:003', 3)])
    def test_a_padded_counter_reports_its_width(self, token: str, width: int) -> None:
        """The width is what makes ports sort as 01, 02 ... 10 rather than 1, 10, 11 ... 2"""
        assert parse_pad_width(token) == width

    @pytest.mark.parametrize('token', ['prefix', 'slot', 'n:', 'n:x', 'nn', '', 'x:02'], ids=str)
    def test_anything_else_is_not_a_numbering_token(self, token: str) -> None:
        """None distinguishes 'not a counter' from 'a counter with no padding'"""
        assert parse_pad_width(token) is None


class TestIsKnownToken:
    """Which tokens this module can render."""

    @pytest.mark.parametrize('token', ['prefix', 'slot', 'n', 'n:02', 'n:0004'])
    def test_the_documented_tokens_are_known(self, token: str) -> None:
        """The four the concept names, the last with any digit width"""
        assert is_known_token(token) is True

    @pytest.mark.parametrize('token', ['slt', 'N', 'number', 'n:x', ''], ids=str)
    def test_anything_else_is_not(self, token: str) -> None:
        """Including a capitalised one - the tokens are lower case and a typo must be refused"""
        assert is_known_token(token) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the refusals                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSyntaxBlockers:
    """What a customer is told before 48 ports are created."""

    def test_a_usable_syntax_is_accepted(self) -> None:
        """The ordinary case"""
        assert syntax_blockers('Gi0/{n}', 24, 1) == []

    @pytest.mark.parametrize('syntax', [None, '', '   ', 5], ids=str)
    def test_an_empty_syntax_is_refused(self, syntax: Any) -> None:
        """It is what the names are generated FROM - there is no default worth guessing"""
        assert PortNameSyntaxError.EMPTY_SYNTAX.value in syntax_blockers(syntax, 1, 1)

    def test_an_unknown_token_is_refused_by_name(self) -> None:
        """
        Refused rather than left in place or dropped

        Leaving it would create ports with a literal brace in the name; dropping it would silently
        produce a batch of duplicates. The message has to name the token AND the allowed ones.
        """
        blockers = syntax_blockers('Gi0/{slt}', 4, 1)

        assert len(blockers) == 1
        assert '{slt}' in blockers[0]
        assert '{prefix}' in blockers[0]

    def test_every_unknown_token_is_reported(self) -> None:
        """A caller fixes one form rather than discovering the typos one submission at a time"""
        assert len(syntax_blockers('{a}-{b}/{n}', 4, 1)) == 2

    def test_an_absurd_pad_width_is_refused(self) -> None:
        """A guard, not a product rule: '{n:99999999}' would turn 48 ports into megabytes of zeroes"""
        blockers = syntax_blockers('{n:99999999}', 4, 1)

        assert any(str(MAX_PAD_WIDTH) in blocker for blocker in blockers)

    def test_the_maximum_pad_width_is_still_allowed(self) -> None:
        """The boundary itself is legal - the guard refuses beyond it, not at it"""
        assert syntax_blockers('{n:%s}' % ('0' * MAX_PAD_WIDTH), 1, 1) == []

    @pytest.mark.parametrize('count', [0, -1, None, 'four', 1.5, True], ids=str)
    def test_an_unusable_count_is_refused(self, count: Any) -> None:
        """
        Including True, because bool is an int subclass in Python

        A count of True would create exactly one port and read as a configuration mistake nobody
        notices.
        """
        assert any('number of ports' in blocker for blocker in syntax_blockers('{n}', count, 1))

    @pytest.mark.parametrize('start_index', [-1, None, 'one', 1.5, True], ids=str)
    def test_an_unusable_start_index_is_refused(self, start_index: Any) -> None:
        """Same reasoning; a negative index would produce names nobody asked for"""
        assert any('start index' in blocker for blocker in syntax_blockers('{n}', 4, start_index))

    def test_zero_is_a_legal_start_index(self) -> None:
        """Some vendors number ports from 0, and the concept sets no floor above it"""
        assert syntax_blockers('Gi0/{n}', 4, 0) == []

    def test_every_reason_is_reported_together(self) -> None:
        """One form, one round trip"""
        assert len(syntax_blockers('', 0, -1)) == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    rendering                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRenderName:
    """One name from one syntax."""

    def test_the_counter_is_substituted(self) -> None:
        """The ordinary case"""
        assert render_name('Gi0/{n}', 3) == 'Gi0/3'

    def test_the_counter_is_padded_to_its_width(self) -> None:
        """What makes a 48-port switch sort correctly in any UI that sorts as text"""
        assert render_name('Gi0/{n:02}', 3) == 'Gi0/03'

    def test_a_number_wider_than_its_padding_is_not_truncated(self) -> None:
        """
        Padding is a MINIMUM width

        Truncating port 100 to '00' under {n:02} would produce a duplicate of port 0 and corrupt the
        batch silently.
        """
        assert render_name('{n:02}', 100) == '100'

    def test_the_prefix_and_the_slot_are_substituted(self) -> None:
        """Both are supplied once for the whole batch"""
        assert render_name('{prefix}-{slot}/{n}', 7, prefix='SW1', slot='2') == 'SW1-2/7'

    def test_absent_prefix_and_slot_render_as_nothing(self) -> None:
        """A syntax may use them and a caller may not supply them"""
        assert render_name('{prefix}{slot}Gi{n}', 1) == 'Gi1'

    def test_a_syntax_without_tokens_renders_itself(self) -> None:
        """Legal for one name; a batch of them is caught by the duplicate check"""
        assert render_name('uplink', 5) == 'uplink'

    def test_a_token_may_repeat(self) -> None:
        """Nothing forbids it, and every occurrence has to be substituted"""
        assert render_name('{n}-{n}', 4) == '4-4'

    def test_an_unknown_token_survives_as_itself(self) -> None:
        """
        Unreachable through the routes, which refuse it first

        Left as the raw token rather than as an empty string so a caller that skipped the validation
        gets output it can recognise instead of a silent batch of duplicates.
        """
        assert render_name('Gi{slt}', 2) == 'Gi{slt}'


class TestGenerateNames:
    """A whole batch."""

    def test_the_batch_counts_up_from_one(self) -> None:
        """The default start index"""
        assert generate_names('Gi0/{n}', 3) == ['Gi0/1', 'Gi0/2', 'Gi0/3']

    def test_the_start_index_is_honoured(self) -> None:
        """So a second batch continues where the first stopped rather than colliding with it"""
        assert generate_names('Gi0/{n}', 3, start_index=25) == ['Gi0/25', 'Gi0/26', 'Gi0/27']

    def test_a_zero_start_index_is_honoured(self) -> None:
        """Some vendors number from 0"""
        assert generate_names('{n}', 2, start_index=0) == ['0', '1']

    def test_the_padding_applies_to_every_name(self) -> None:
        """The whole batch sorts as text, which is the point"""
        assert generate_names('{n:02}', 3, start_index=9) == ['09', '10', '11']

    def test_the_prefix_and_slot_are_the_same_for_the_whole_batch(self) -> None:
        """They are supplied once - only the counter moves"""
        assert generate_names('{prefix}{n}', 2, prefix='X') == ['X1', 'X2']

    def test_a_count_of_one_produces_one_name(self) -> None:
        """The smallest legal batch"""
        assert generate_names('Gi0/{n}', 1) == ['Gi0/1']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   collisions                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDuplicateNames:
    """Names a batch produces more than once."""

    def test_a_numbered_batch_has_none(self) -> None:
        """The ordinary case"""
        assert duplicate_names(generate_names('Gi0/{n}', 24)) == []

    def test_a_syntax_without_a_counter_repeats_itself(self) -> None:
        """
        The mistake this exists for

        Without it the unique index would refuse the second port mid-batch and leave a half-created
        device behind.
        """
        assert duplicate_names(generate_names('uplink', 3)) == ['uplink']

    def test_each_duplicate_is_reported_once(self) -> None:
        """A batch of 48 identical names is one problem, not 47"""
        assert duplicate_names(['a', 'a', 'a', 'b', 'b']) == ['a', 'b']

    def test_an_empty_batch_has_no_duplicates(self) -> None:
        """Nothing to repeat"""
        assert duplicate_names([]) == []


class TestCollidingNames:
    """Generated names an existing port already carries."""

    def test_a_free_face_has_no_collisions(self) -> None:
        """The ordinary case for a new device"""
        assert colliding_names(['Gi0/1', 'Gi0/2'], set()) == []

    def test_a_taken_name_is_reported(self) -> None:
        """
        The customer adding a second batch to a switch learns which names clash BEFORE half is written

        Otherwise the unique (object_id, side, name) index refuses them one at a time.
        """
        assert colliding_names(['Gi0/1', 'Gi0/2'], {'Gi0/2'}) == ['Gi0/2']

    def test_the_generated_order_is_kept(self) -> None:
        """The report reads alongside the preview, which is in generation order"""
        assert colliding_names(['a', 'b', 'c'], {'c', 'a'}) == ['a', 'c']

    def test_each_collision_is_reported_once(self) -> None:
        """A name the batch itself repeats is one collision, not several"""
        assert colliding_names(['a', 'a'], {'a'}) == ['a']

    def test_an_empty_batch_collides_with_nothing(self) -> None:
        """Nothing to compare"""
        assert colliding_names([], {'a'}) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    constants                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_syntax_tokens_are_pinned() -> None:
    """
    The token names are a user-facing contract

    They appear in the customer's saved syntaxes and in the refusal messages, so renaming one would
    break every stored form and every piece of documentation at once.
    """
    assert {member.name: member.value for member in SyntaxToken} == {
        'PREFIX': 'prefix',
        'SLOT': 'slot',
        'NUMBER': 'n',
    }

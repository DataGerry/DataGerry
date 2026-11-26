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
Unit tests for the scope building blocks (phase 9 steps 4-6, phase 10): user tokens, ``within`` and ``in_network`` -
their shape, canonical form, casting, compiled fragments, the tokens a scope needs, the resolver (manager stood in) and
the stale-selector rule

Pinned: blocks with an object id (``related_to`` with an optional relation id, phase 11) (a CIDR too for networks, written in its network form); a token only as the
whole value of equals / in / contains and only on a person selector selecting its kind; tokens compiled from the
resolved context - an unresolved one matches nothing; ``within`` and ``in_network`` compiled onto the materialised
scope block (L itself or a chain naming it, a network id named, a CIDR as one address range); the resolver's reads
(linked persons / person groups); a person selector dropping a token's kind is stale
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.scope_compiler import (
    MULTIPLE_PERSON_KIND,
    ScopeContext,
    ScopeField,
    ScopeMessage,
    ScopeReferences,
    ScopeResolver,
    canonical_blocks,
    cast_scope,
    compile_scope,
    field_views,
    scope_references,
    scope_shape_problems,
    type_change_problems,
)
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.scope_compiler import ScopeResolutionError
# -------------------------------------------------------------------------------------------------------------------- #

NOW: datetime = datetime(2026, 11, 25, tzinfo=timezone.utc)
PERSON: dict[str, str] = {'user': 'person'}
GROUPS: dict[str, str] = {'user': 'groups'}
OWNER: ScopeField = ScopeField('person', selectable=frozenset({'PERSON'}))
TEAM: ScopeField = ScopeField(MULTIPLE_PERSON_KIND, selectable=frozenset({'PERSON', 'PERSON_GROUP'}))


class TestShape:
    """9.1 extended"""

    @pytest.mark.parametrize('block', [
        {'within': 7}, {'in_network': 3}, {'in_network': '10.1.2.3/16'}, {'in_network': 'fd00::/8'},
        {'field': 'owner', 'op': 'equals', 'value': PERSON}, {'field': 'team', 'op': 'contains', 'value': GROUPS},
        {'field': 'owner', 'op': 'in', 'value': GROUPS}, {'related_to': 9}, {'related_to': 9, 'relation': 2},
    ], ids=['within', 'network-id', 'cidr', 'ipv6', 'token-equals', 'token-contains', 'token-in', 'related-to',
            'related-to-a-relation'])
    def test_well_formed_blocks(self, block: dict[str, Any]) -> None:
        """No problem"""
        assert not scope_shape_problems([block])

    @pytest.mark.parametrize('block, expected', [
        ({'within': 0}, ScopeMessage.BAD_LOCATION.value.format(position=1)),
        ({'within': True}, ScopeMessage.BAD_LOCATION.value.format(position=1)),
        ({'within': 'Fulda'}, ScopeMessage.BAD_LOCATION.value.format(position=1)),
        ({'in_network': '10.0.0.0'}, ScopeMessage.BAD_NETWORK.value.format(position=1, value='"10.0.0.0"')),
        ({'in_network': '10.0.0.0/99'}, ScopeMessage.BAD_NETWORK.value.format(position=1, value='"10.0.0.0/99"')),
        ({'within': 1, 'in_network': 2}, ScopeMessage.UNKNOWN_KEYS.value.format(position=1,
                                                                                 keys=['in_network', 'within'])),
        ({'field': 'o', 'op': 'equals', 'value': {'user': 'me'}},
         ScopeMessage.BAD_TOKEN.value.format(position=1, value='{"user": "me"}')),
        ({'field': 'o', 'op': 'not_equals', 'value': PERSON},
         ScopeMessage.TOKEN_NOT_FOR_OPERATOR.value.format(position=1)),
        ({'field': 'o', 'op': 'in', 'value': [PERSON]},
         ScopeMessage.NOT_A_SCALAR.value.format(position=1, value='{"user": "person"}')),
        ({'related_to': 0}, ScopeMessage.BAD_RELATED_TO.value.format(position=1)),
        ({'related_to': 'srv'}, ScopeMessage.BAD_RELATED_TO.value.format(position=1)),
        ({'related_to': 9, 'relation': True}, ScopeMessage.BAD_RELATED_TO.value.format(position=1)),
        ({'related_to': 9, 'relation': None}, ScopeMessage.BAD_RELATED_TO.value.format(position=1)),
        ({'related_to': 9, 'within': 2}, ScopeMessage.UNKNOWN_KEYS.value.format(position=1,
                                                                                 keys=['related_to', 'within'])),
        ({'relation': 2}, ScopeMessage.UNKNOWN_KEYS.value.format(position=1, keys=['relation'])),
    ], ids=['zero', 'boolean', 'a-name', 'no-prefix', 'bad-prefix', 'two-keys', 'unknown-token', 'token-negation',
            'token-in-a-list', 'related-zero', 'related-a-name', 'relation-boolean', 'relation-null',
            'related-and-within', 'relation-alone'])
    def test_malformed_blocks(self, block: dict[str, Any], expected: str) -> None:
        """Named by position"""
        assert scope_shape_problems([block]) == [expected]

    def test_a_cidr_is_stored_in_its_network_form(self) -> None:
        """Host bits dropped - two spellings, one scope"""
        assert canonical_blocks([{'in_network': '10.1.2.3/16'}]) == canonical_blocks([{'in_network': '10.1.0.0/16'}])


class TestCasting:
    """9.3 extended"""

    @pytest.mark.parametrize('field, op, token', [(OWNER, 'equals', PERSON), (TEAM, 'contains', GROUPS)],
                             ids=['own-person', 'my-groups'])
    def test_a_token_on_a_selector_of_its_kind_passes_unchanged(self, field: ScopeField, op: str,
                                                                token: dict[str, str]) -> None:
        """Kept for the per-user resolution"""
        block = {'field': 'f', 'op': op, 'value': token}

        assert cast_scope([block], {'f': field}) == ([block], [])

    @pytest.mark.parametrize('field, token, marker', [
        (OWNER, GROUPS, 'PERSON_GROUP'), (ScopeField('ref'), PERSON, 'PERSON'),
    ], ids=['selector-without-groups', 'not-a-selector'])
    def test_a_token_elsewhere_is_refused(self, field: ScopeField, token: dict[str, str], marker: str) -> None:
        """Names the field, the token and the kind"""
        _blocks, problems = cast_scope([{'field': 'f', 'op': 'equals', 'value': token}], {'f': field})

        assert problems == [ScopeMessage.TOKEN_NOT_FOR_FIELD.value.format(field='f', token=token['user'], kind=marker)]

    def test_the_one_key_blocks_pass_without_a_field(self) -> None:
        """Nothing to cast"""
        blocks = [{'within': 3}, {'in_network': '10.0.0.0/8'}]

        assert cast_scope(blocks, {}) == (blocks, [])

    def test_a_person_selectors_selectable_kinds_are_viewed(self) -> None:
        """From the field definition"""
        views = field_views([{'name': 'o', 'type': 'person', 'selectable': ['PERSON_GROUP']}], [])

        assert views['o'].selectable == frozenset({'PERSON_GROUP'})


class TestCompile:
    """9.2 extended, the location and network blocks on the scope block (phase 10)"""

    CONTEXT: ScopeContext = ScopeContext(person_ids=(5,), group_ids=(6, 7))

    def test_every_block(self) -> None:
        """Tokens resolved; within, a network id and a CIDR read the scope block"""
        scope = [{'field': 'owner', 'op': 'equals', 'value': PERSON},
                 {'field': 'team', 'op': 'contains', 'value': GROUPS}, {'within': 3}, {'in_network': 20},
                 {'in_network': '10.0.0.0/8'}]

        compiled = compile_scope(scope, {'owner': OWNER, 'team': TEAM}, NOW, self.CONTEXT)['$and']

        assert compiled == [
            {'fields': {'$elemMatch': {'name': 'owner', 'value': {'$in': [5]}}}},
            {'fields': {'$elemMatch': {'name': 'team', 'value': {'$in': [6, 7]}}}},
            {'$or': [{'public_id': 3}, {'_scope.locations': 3}]},
            {'_scope.networks': 20},
            {'_scope.ips': {'$elemMatch': {'$gte': '4:0a000000', '$lte': '4:0affffff'}}},
        ]

    def test_related_to_reads_the_related_list(self) -> None:
        """Either end; with a relation, that relation only"""
        compiled = compile_scope([{'related_to': 9}, {'related_to': 8, 'relation': 2}], {}, NOW)['$and']

        assert compiled == [{'_scope.related': {'$elemMatch': {'object': 9}}},
                            {'_scope.related': {'$elemMatch': {'object': 8, 'relation': 2}}}]

    def test_an_ipv6_cidr_is_one_range_of_its_version(self) -> None:
        """32 hex digits behind 6:"""
        compiled = compile_scope([{'in_network': 'fd00::/64'}], {}, NOW)['$and'][0]

        assert compiled['_scope.ips']['$elemMatch'] == {'$gte': '6:fd000000000000000000000000000000',
                                                        '$lte': '6:fd00000000000000ffffffffffffffff'}

    def test_unresolved_tokens_match_nothing(self) -> None:
        """No context: empty $in; within needs no context"""
        compiled = compile_scope([{'field': 'owner', 'op': 'equals', 'value': PERSON}, {'within': 9}],
                                 {'owner': OWNER}, NOW)['$and']

        assert compiled == [{'fields': {'$elemMatch': {'name': 'owner', 'value': {'$in': []}}}},
                            {'$or': [{'public_id': 9}, {'_scope.locations': 9}]}]


def test_scope_references_collects_the_tokens() -> None:
    """Across scopes; the location and network blocks need nothing resolved"""
    references = scope_references([[{'within': 3}, {'field': 'o', 'op': 'equals', 'value': PERSON}],
                                   [{'in_network': 8}, {'field': 'o', 'op': 'equals', 'value': 'x'}]])

    assert references == ScopeReferences(person=True, groups=False)


def _resolver(objects: list[Any]) -> tuple[ScopeResolver, MagicMock]:
    """A resolver whose object reads answer in turn"""
    objects_manager = MagicMock()
    objects_manager.find.side_effect = objects

    return ScopeResolver(objects_manager), objects_manager


class TestResolver:
    """The reads, stood in"""

    USER: Any = MagicMock(public_id=12, group_ids=[2, 3])

    def test_tokens_read_the_sync_links(self) -> None:
        """The user's person, the person groups of the user's groups"""
        resolver, objects = _resolver([[{'public_id': 50}], [{'public_id': 61}, {'public_id': 60}]])

        context = resolver.resolve(self.USER, ScopeReferences(person=True, groups=True))

        assert (context.person_ids, context.group_ids) == ((50,), (60, 61))
        assert objects.find.call_args_list[0].kwargs['criteria'] == {'system_ref.kind': 'user',
                                                                       'system_ref.id': {'$in': [12]}}
        assert objects.find.call_args_list[1].kwargs['criteria'] == {'system_ref.kind': 'user_group',
                                                                       'system_ref.id': {'$in': [2, 3]}}

    def test_a_user_without_groups_reads_no_group_link(self) -> None:
        """Only the person is looked up"""
        resolver, objects = _resolver([[{'public_id': 50}]])

        context = resolver.resolve(MagicMock(public_id=12, group_ids=[]), ScopeReferences(person=True, groups=True))

        assert (context.person_ids, context.group_ids) == ((50,), ())
        assert objects.find.call_count == 1

    def test_nothing_named_reads_nothing(self) -> None:
        """No token, no read"""
        resolver, objects = _resolver([])

        assert resolver.resolve(self.USER, ScopeReferences()) == ScopeContext()
        objects.find.assert_not_called()

    def test_a_failed_read_is_the_resolution_error(self) -> None:
        """Carrying the cause"""
        cause = BaseManagerGetError('down')
        resolver, _objects = _resolver([cause])

        with pytest.raises(ScopeResolutionError) as raised:
            resolver.resolve(self.USER, ScopeReferences(person=True))

        assert raised.value.args[0] is cause


def test_a_selector_dropping_a_tokens_kind_is_stale() -> None:
    """The person selector stops selecting person groups"""
    assignment = {'public_id': 11, 'role_id': 1, 'scope': [{'field': 'team', 'op': 'contains', 'value': GROUPS}]}
    narrowed = ScopeField(MULTIPLE_PERSON_KIND, selectable=frozenset({'PERSON'}))

    assert type_change_problems(5, {'team': TEAM}, {'team': narrowed}, [assignment]) == [
        ScopeMessage.STALE_SELECTABLE.value.format(field='team', type_id=5, kind='PERSON_GROUP', assignment_ids=[11])]

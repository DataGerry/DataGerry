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
Unit tests for cmdb.framework.ci_explorer.label_field

The write-side counterpart of `nodes.resolve_title`: which field a CmdbType may nominate as the value
its CI Explorer nodes show. Pure - every rule is judged against a type document handed in, so an
update can be judged against the payload being written rather than the stored document.

Two refusals carry the whole module. A name the Type does not declare renders every node of the Type
as "Label not selected", which is indistinguishable from never having chosen one - so it is caught at
the write. A multi-data-section field WOULD resolve (an MDS field has an entry in the object's flat
`fields` list too) but to the wrong thing: the per-row data lives in `multi_data_sections`, so the
node would show a blank or a single stale value instead of the rows.
"""
from typing import Any

import pytest

from cmdb.framework.ci_explorer.label_field import (
    declared_field_names,
    is_label_field_unset,
    label_field_error,
    mds_field_names,
    selectable_label_fields,
    NO_SELECTABLE_FIELDS,
)
from cmdb.framework.ci_explorer.nodes import resolve_title
# -------------------------------------------------------------------------------------------------------------------- #

PLAIN_FIELD: str = 'hostname'
SECOND_FIELD: str = 'serial'
MDS_FIELD: str = 'port-name'
UNASSIGNED_FIELD: str = 'orphan'


def _type_doc(**overrides: Any) -> dict[str, Any]:
    """A CmdbType with one plain section, one multi-data-section and one unassigned field."""
    document: dict[str, Any] = {
        'public_id': 10,
        'name': 'server',
        'fields': [
            {'name': PLAIN_FIELD, 'type': 'text'},
            {'name': SECOND_FIELD, 'type': 'text'},
            {'name': MDS_FIELD, 'type': 'text'},
            {'name': UNASSIGNED_FIELD, 'type': 'text'},
        ],
        'render_meta': {
            'sections': [
                {'type': 'section', 'name': 'information', 'fields': [PLAIN_FIELD, SECOND_FIELD]},
                {'type': 'multi-data-section', 'name': 'ports', 'fields': [MDS_FIELD]},
            ],
        },
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 reading the Type                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadingTheType:
    """The three readers the rule is composed of."""

    def test_declared_field_names_reads_the_flat_list(self) -> None:
        """A Type declares every field it has in `fields`; its sections only reference them by name"""
        assert declared_field_names(_type_doc()) == [PLAIN_FIELD, SECOND_FIELD, MDS_FIELD, UNASSIGNED_FIELD]

    def test_mds_field_names_reads_the_section_kind(self) -> None:
        """A field is MDS by where its NAME is listed, not by anything on the field itself"""
        assert mds_field_names(_type_doc()) == {MDS_FIELD}

    def test_a_section_carrying_whole_field_dicts_is_read_too(self) -> None:
        """Older documents spell a section's `fields` as dicts rather than names"""
        document = _type_doc()
        document['render_meta']['sections'][1]['fields'] = [{'name': MDS_FIELD, 'type': 'text'}]

        assert mds_field_names(document) == {MDS_FIELD}

    def test_an_unreadable_entry_in_a_section_is_skipped(self) -> None:
        """A section listing something that is neither a name nor a field dict does not stop the scan"""
        document = _type_doc()
        document['render_meta']['sections'][1]['fields'] = [None, 7, MDS_FIELD]

        assert mds_field_names(document) == {MDS_FIELD}

    def test_selectable_excludes_the_mds_fields(self) -> None:
        """What the refusal messages offer, and what a frontend picker would show"""
        assert selectable_label_fields(_type_doc()) == [PLAIN_FIELD, SECOND_FIELD, UNASSIGNED_FIELD]

    ALL_FIELDS: list[str] = [PLAIN_FIELD, SECOND_FIELD, MDS_FIELD, UNASSIGNED_FIELD]

    @pytest.mark.parametrize('broken, expected', [
        ({'fields': 'nonsense'}, []),
        ({'fields': [None, 'x', {'label': 'no name'}]}, []),
        ({'render_meta': 'nonsense'}, ALL_FIELDS),
        ({'render_meta': {'sections': 'nonsense'}}, ALL_FIELDS),
    ], ids=['fields', 'field entries', 'render_meta', 'sections'])
    def test_a_malformed_type_is_read_without_crashing(
        self, broken: dict[str, Any], expected: list[str],
    ) -> None:
        """
        The rule never crashes on a shape the structure rules are there to judge

        It runs on a write payload, which may be anything until the other guards have had their say.
        An unreadable field list offers nothing; an unreadable section list only means no field is
        known to be MDS, so every declared field stays selectable.
        """
        assert selectable_label_fields(_type_doc(**broken)) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the nomination rule                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRule:
    """label_field_error - the one rule every write path shares."""

    @pytest.mark.parametrize('nominated', [PLAIN_FIELD, SECOND_FIELD], ids=str)
    def test_a_field_of_an_ordinary_section_is_usable(self, nominated: str) -> None:
        """The ordinary case: the nodes show that field's value per object"""
        assert label_field_error(_type_doc(), nominated) is None

    def test_a_declared_but_unassigned_field_is_usable(self) -> None:
        """
        Accepted deliberately

        The frontend only offers fields it can show in a section, but an unassigned field still
        resolves on the object - and refusing it here would refuse a Type shape the write routes
        otherwise allow.
        """
        assert label_field_error(_type_doc(), UNASSIGNED_FIELD) is None

    @pytest.mark.parametrize('nominated', [None, ''], ids=['null', 'empty'])
    def test_nominating_nothing_is_usable(self, nominated: Any) -> None:
        """"No field chosen" is a legitimate state - it is what every Type starts in"""
        assert label_field_error(_type_doc(), nominated) is None
        assert is_label_field_unset(nominated) is True

    def test_a_name_the_type_does_not_declare_is_refused(self) -> None:
        """The defect this rule exists for: a display string sent where a field name belongs"""
        error = label_field_error(_type_doc(), 'Switch')

        assert error is not None
        assert 'Switch' in error
        assert PLAIN_FIELD in error  # the message offers what the Type does have

    def test_an_mds_field_is_refused_with_its_own_message(self) -> None:
        """It would resolve, but to a flat entry that carries none of the section's rows"""
        error = label_field_error(_type_doc(), MDS_FIELD)

        assert error is not None
        assert 'multi-data-section' in error

    @pytest.mark.parametrize('nominated', [7, True, ['hostname'], {'name': 'hostname'}], ids=str)
    def test_a_non_string_is_refused(self, nominated: Any) -> None:
        """The Cerberus schema catches this on the routes; the rule does not rely on that"""
        assert label_field_error(_type_doc(), nominated) is not None

    def test_a_type_with_nothing_to_offer_says_so(self) -> None:
        """A fieldless Type still has to produce a readable refusal"""
        error = label_field_error(_type_doc(fields=[]), 'hostname')

        assert error is not None
        assert NO_SELECTABLE_FIELDS in error


# -------------------------------------------------------------------------------------------------------------------- #
#                                            agreement with the read side                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAgreementWithResolveTitle:
    """What the rule accepts is what the graph can actually resolve - the point of the whole module."""

    def test_an_accepted_nomination_resolves_on_an_object(self) -> None:
        """The write rule and `nodes.resolve_title` read the same key the same way"""
        type_doc = _type_doc(ci_explorer_label=PLAIN_FIELD)
        obj = {'fields': [{'name': PLAIN_FIELD, 'value': 'srv-01'}]}

        assert label_field_error(type_doc, type_doc['ci_explorer_label']) is None
        assert resolve_title(obj, type_doc) == 'srv-01'

    def test_a_refused_nomination_is_exactly_what_renders_unlabelled(self) -> None:
        """`resolve_title` returns None for it, which the frontend draws as "Label not selected\""""
        type_doc = _type_doc(ci_explorer_label='Switch')
        obj = {'fields': [{'name': PLAIN_FIELD, 'value': 'srv-01'}]}

        assert label_field_error(type_doc, type_doc['ci_explorer_label']) is not None
        assert resolve_title(obj, type_doc) is None

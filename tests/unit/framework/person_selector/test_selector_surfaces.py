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
Unit tests for cmdb.framework.person_selector.selector_surfaces - every person surface of a rendered object

One rendered object carries every surface: its own selector (flat + a multi-data row), its own summaries, a
reference whose summaries and marked line hold persons, a reference section pulling a person field in (and a nested
one), and three external links - one filled with a visible person, one with a hidden one, one with none. Ada is
visible, Eve is not. Pinned: the ids of every surface are collected; ``apply`` rewrites each surface to the visible
selections and removes every marker; the renderer's write helpers raw-keep only person values
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.person_selector.person_selector_constants import PersonLineMarkerKey, PersonRenderMarker
from cmdb.framework.person_selector.selector_surfaces import (
    PersonSurfaces,
    apply_to_reference,
    collect_render_surfaces,
    mark_link_person_ids,
    mark_reference_line,
    reference_person_ids,
    summary_value,
)
# -------------------------------------------------------------------------------------------------------------------- #

ADA: int = 21
EVE: int = 22
BOB: int = 23
OBJECT_ID: int = 5
TYPE_LABEL: str = 'Thing'
OWNER: str = 'owner'
LINE_TEMPLATE: str = '{} / {}'
OTHER_SUMMARY: str = 'x'

VISIBLE: dict[int, dict[str, Any]] = {
    ADA: {'object_id': ADA, 'label': 'Ada'},
    BOB: {'object_id': BOB, 'label': 'Bob'},
}
OBJECT_TYPE: Any = SimpleNamespace(
    label=TYPE_LABEL,
    fields=[{'type': 'person', 'name': OWNER, 'selectable': ['PERSON'], 'multiple': True}],
)


def _reference() -> dict[str, Any]:
    """A reference payload whose summaries and marked line hold Ada and Eve"""
    return {
        'object_id': 9, 'line': 'raw line',
        'summaries': [{'value': [ADA, EVE], 'type': 'person'}, {'value': OTHER_SUMMARY, 'type': 'text'}],
        PersonRenderMarker.LINE.value: {
            PersonLineMarkerKey.TEMPLATE.value: LINE_TEMPLATE,
            PersonLineMarkerKey.INPUTS.value: [[ADA, EVE], OTHER_SUMMARY],
        },
    }


def _result() -> RenderResult:
    """A rendered object carrying every surface"""
    result = RenderResult()
    result.object_information = {'object_id': OBJECT_ID}
    result.fields = [
        {'name': OWNER, 'type': 'person', 'multiple': True, 'value': [ADA, EVE]},
        {'name': 'asset', 'type': 'ref', 'value': 9, 'reference': _reference()},
        {'name': 'pulled-field', 'type': 'ref-section-field', 'references': {'fields': [
            {'name': 'single', 'type': 'person', 'multiple': False, 'value': EVE},
            {'name': 'inner-field', 'type': 'ref-section-field', 'references': {'fields': [
                {'name': 'several', 'type': 'person', 'multiple': True, 'value': [EVE, BOB]},
            ]}},
        ]}},
    ]
    result.multi_data_sections = [{'section_id': 's', 'values': [{'multi_data_id': 0, 'data': [
        {'name': OWNER, 'value': [EVE, ADA]},
    ]}]}]
    result.summaries = [{'name': 'n', 'type': 'text', 'value': 'n1'},
                        {'name': OWNER, 'type': 'person', 'value': [ADA, EVE]}]
    result.summary_line = 'raw'
    result.externals = [
        {'name': 'visible', PersonRenderMarker.LINK_IDS.value: [ADA]},
        {'name': 'hidden', PersonRenderMarker.LINK_IDS.value: [ADA, EVE]},
        {'name': 'plain'},
    ]

    return result


def _applied() -> RenderResult:
    """The rendered object after the pass"""
    result: RenderResult = _result()
    collect_render_surfaces(result, OBJECT_TYPE).apply(VISIBLE)

    return result


def test_the_ids_of_every_surface_are_collected() -> None:
    """Own field, row, summaries, reference, pulled + nested pulled field, links"""
    surfaces: PersonSurfaces = collect_render_surfaces(_result(), OBJECT_TYPE)

    assert surfaces.ids() == {ADA, EVE, BOB}


def test_a_type_without_person_summaries_builds_no_default_line() -> None:
    """The default line is only needed - and only built - for a person summary"""
    result = RenderResult()
    result.fields, result.summaries = [], [{'name': 'n', 'type': 'text', 'value': 'n1'}]

    assert collect_render_surfaces(result, SimpleNamespace(fields=[])).default_line == ''


def test_the_own_selector_and_its_row_keep_the_visible_ids() -> None:
    """The flat field gets persons, the row keeps ids only"""
    result: RenderResult = _applied()

    assert result.fields[0]['value'] == [ADA]
    assert result.fields[0]['persons'] == [VISIBLE[ADA]]
    assert result.multi_data_sections[0]['values'][0]['data'][0] == {'name': OWNER, 'value': [ADA]}


def test_the_own_summaries_and_line_show_the_visible_labels() -> None:
    """The line is joined again"""
    result: RenderResult = _applied()

    assert [entry['value'] for entry in result.summaries] == ['n1', 'Ada']
    assert result.summary_line == 'n1 | Ada'


def test_a_reference_shows_the_visible_labels_and_its_line_is_filled_again() -> None:
    """The marker is removed"""
    reference: dict[str, Any] = _applied().fields[1]['reference']

    assert [entry['value'] for entry in reference['summaries']] == ['Ada', OTHER_SUMMARY]
    assert reference['line'] == LINE_TEMPLATE.format('Ada', OTHER_SUMMARY)
    assert PersonRenderMarker.LINE.value not in reference


def test_pulled_person_fields_are_judged_by_their_own_definition() -> None:
    """One holding one (hidden -> None) and one holding several, a level down"""
    pulled: list[dict[str, Any]] = _applied().fields[2]['references']['fields']
    nested: dict[str, Any] = pulled[1]['references']['fields'][0]

    assert (pulled[0]['value'], pulled[0]['persons']) == (None, [])
    assert (nested['value'], nested['persons']) == ([BOB], [VISIBLE[BOB]])


def test_a_link_filled_with_a_hidden_person_is_left_out_and_markers_go() -> None:
    """The unmarked link is untouched"""
    assert _applied().externals == [{'name': 'visible'}, {'name': 'plain'}]


def test_a_lone_reference_is_rewritten_alone() -> None:
    """The MDS reference route's payload"""
    reference: dict[str, Any] = _reference()

    assert reference_person_ids(reference) == {ADA, EVE}

    apply_to_reference(reference, VISIBLE)

    assert reference['line'] == LINE_TEMPLATE.format('Ada', OTHER_SUMMARY)


@pytest.mark.parametrize('field_type, stored, expected', [
    ('person', [ADA], [ADA]),
    ('person', None, None),
    ('text', 'web01', 'web01'),
    ('number', 3, '3'),
], ids=['person-raw', 'person-empty-raw', 'text', 'other-as-text'])
def test_a_summary_value_is_raw_only_for_a_person(field_type: str, stored: Any, expected: Any) -> None:
    """The person pass labels the raw ones"""
    assert summary_value({'type': field_type}, stored) == expected


def test_a_line_is_marked_only_when_a_summary_holds_a_person() -> None:
    """The template and the inputs in placeholder order"""
    plain: dict[str, Any] = {}
    marked: dict[str, Any] = {}
    mark_reference_line(plain, LINE_TEMPLATE, [{'type': 'text', 'value': 'a'}])
    mark_reference_line(marked, LINE_TEMPLATE, [{'type': 'person', 'value': [ADA]}, {'type': 'text', 'value': 'a'}])

    assert not plain
    assert marked[PersonRenderMarker.LINE.value] == {
        PersonLineMarkerKey.TEMPLATE.value: LINE_TEMPLATE, PersonLineMarkerKey.INPUTS.value: [[ADA], 'a'],
    }


def test_a_link_is_marked_only_when_filled_from_a_person_selector() -> None:
    """The ids of every person value it was filled with"""
    selectors: dict[str, dict[str, Any]] = {OWNER: {}}
    plain: dict[str, Any] = {}
    marked: dict[str, Any] = {}
    mark_link_person_ids(plain, ['name'], ['web01'], selectors)
    mark_link_person_ids(marked, ['name', OWNER], ['web01', [ADA, EVE]], selectors)

    assert not plain
    assert marked[PersonRenderMarker.LINK_IDS.value] == [ADA, EVE]

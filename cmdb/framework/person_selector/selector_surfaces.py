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
Every place a rendered CmdbObject shows a person selection, gathered for the person pass

The renderer writes person values RAW wherever it builds something from a stored value, and the person pass
(``selector_render.apply_person_selector_render``) collects the ids of every surface, resolves them once and rewrites
each surface to what the reader may see:

  - the object's own flat selectors - ``persons`` added - and multi-data rows - ids only; judged by its Type
  - person fields pulled into a reference section, nested sections included - judged by their own pulled
    definition, ``persons`` added
  - reference payloads, the object's own and those pulled into a section: a person summary value becomes its labels,
    and a line marked ``PersonRenderMarker.LINE`` is filled again with them
  - the object's own summaries: a person value becomes its labels, and the summary line is joined again
  - external links marked ``PersonRenderMarker.LINK_IDS``: a link filled with an id the reader may not see is left out

Labels are ``selector_text.visible_labels_text``. Every marker is removed, whatever the reader sees
"""
from dataclasses import dataclass, field
from typing import Any, Mapping

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey
from cmdb.models.type_model.person_selector_rules import is_multiple
from cmdb.framework.rendering.render_constants import RenderedFieldKey, RenderObjectInfoKey
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.rendering.summary_line import default_summary_line, join_summary_line
from cmdb.framework.person_selector.person_selector_constants import PersonLineMarkerKey, PersonRenderMarker
from cmdb.framework.person_selector.selector_text import kept_value, visible_labels_text, visible_selections
from cmdb.framework.person_selector.selector_values import ids_of, selector_fields
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonSurfaces',
    'collect_render_surfaces',
    'reference_person_ids',
    'apply_to_reference',
    'summary_value',
    'mark_reference_line',
    'mark_link_person_ids',
]


@dataclass
class PersonSurfaces:
    """
    The person surfaces of one rendered object

    Attributes:
        result (RenderResult): The rendered object, changed in place by ``apply``
        default_line (str): Its summary line without summary values - only built when a person summary needs it
        expanded (list[tuple[dict[str, Any], bool]]): Selector fields that get ``persons`` - flat and pulled in - each
            with whether it holds several
        rows (list[tuple[dict[str, Any], bool]]): Selector entries of multi-data rows, each with whether it holds
            several
        references (list[dict[str, Any]]): Reference payloads, own and pulled in
        summaries (list[dict[str, Any]]): The own summary entries of person fields
    """
    result: RenderResult
    default_line: str
    expanded: list[tuple[dict[str, Any], bool]] = field(default_factory=list)
    rows: list[tuple[dict[str, Any], bool]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)

    def ids(self) -> set[int]:
        """
        Every person id the rendered object shows anywhere

        Returns:
            set[int]: The ids to resolve
        """
        ids: set[int] = {
            object_id
            for entry, _ in self.expanded + self.rows
            for object_id in ids_of(entry.get(FieldKey.VALUE.value))
        }
        ids.update(object_id for entry in self.summaries for object_id in ids_of(entry.get(FieldKey.VALUE.value)))

        for reference in self.references:
            ids |= reference_person_ids(reference)

        for link in self.result.externals or []:
            ids.update(ids_of(link.get(PersonRenderMarker.LINK_IDS.value)))

        return ids

    def apply(self, visible: Mapping[int, dict[str, Any]]) -> None:
        """
        Rewrites every surface to what the reader may see, and removes the markers

        Args:
            visible (Mapping[int, dict[str, Any]]): The selections the reader may see, by id
        """
        for entry, multiple in self.expanded:
            entry[FieldKey.VALUE.value] = kept_value(entry.get(FieldKey.VALUE.value), multiple, visible)
            entry[RenderedFieldKey.PERSONS.value] = visible_selections(entry[FieldKey.VALUE.value], visible)

        for entry, multiple in self.rows:
            stored: Any = entry.get(CmdbObjectFieldKey.VALUE.value)
            entry[CmdbObjectFieldKey.VALUE.value] = kept_value(stored, multiple, visible)

        for reference in self.references:
            apply_to_reference(reference, visible)

        for entry in self.summaries:
            entry[FieldKey.VALUE.value] = visible_labels_text(entry.get(FieldKey.VALUE.value), visible)

        if self.summaries:
            self.result.summary_line = join_summary_line(self.result.summaries, self.default_line)

        self.result.externals = _visible_links(self.result.externals, visible)


def collect_render_surfaces(result: RenderResult, object_type: CmdbType) -> PersonSurfaces:
    """
    Gathers the person surfaces of one rendered object

    Args:
        result (RenderResult): The rendered object
        object_type (CmdbType): Its Type, which declares its own selectors

    Returns:
        PersonSurfaces: Every surface showing a selection, none read yet
    """
    selectors: dict[str, dict[str, Any]] = selector_fields(object_type.fields)
    summaries: list[dict[str, Any]] = [entry for entry in result.summaries or [] if _is_person_field(entry)]
    surfaces = PersonSurfaces(
        result=result,
        default_line=default_summary_line(
            object_type.label, (result.object_information or {}).get(RenderObjectInfoKey.OBJECT_ID.value),
        ) if summaries else '',
        summaries=summaries,
    )

    for rendered_field in result.fields or []:
        name: Any = rendered_field.get(FieldKey.NAME.value)

        if name in selectors:
            surfaces.expanded.append((rendered_field, is_multiple(selectors[name])))
        else:
            _collect_field(rendered_field, surfaces)

    surfaces.rows = [(entry, is_multiple(selectors[entry[CmdbObjectFieldKey.NAME.value]]))
                     for entry in _row_entries(result, selectors)]

    return surfaces


def _collect_field(rendered_field: dict[str, Any], surfaces: PersonSurfaces) -> None:
    """
    Gathers what a rendered field that is no own selector shows: its reference, or the fields of its section

    Args:
        rendered_field (dict[str, Any]): A rendered field - own, or pulled into a reference section
        surfaces (PersonSurfaces): Where the surfaces are gathered (changed in place)
    """
    reference: Any = rendered_field.get(RenderedFieldKey.REFERENCE.value)

    if isinstance(reference, dict):
        surfaces.references.append(reference)

    section: Any = rendered_field.get(RenderedFieldKey.REFERENCES.value)

    if not isinstance(section, dict):
        return

    for pulled in section.get(RenderedFieldKey.FIELDS.value) or []:
        if not isinstance(pulled, dict):
            continue

        if _is_person_field(pulled):
            surfaces.expanded.append((pulled, is_multiple(pulled)))
        else:
            _collect_field(pulled, surfaces)


def _row_entries(result: RenderResult, selectors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The selector entries of every multi-data row of a rendered object"""
    return [
        entry
        for section in result.multi_data_sections or [] if isinstance(section, dict)
        for row in section.get(CmdbObjectMdsKey.VALUES.value) or [] if isinstance(row, dict)
        for entry in row.get(CmdbObjectMdsRowKey.DATA.value) or []
        if isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) in selectors
    ]


def _is_person_field(entry: dict[str, Any]) -> bool:
    """Whether a rendered field or summary entry is of the person kind"""
    return entry.get(FieldKey.TYPE.value) == FieldType.PERSON.value


def _visible_links(links: list[dict[str, Any]] | None, visible: Mapping[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """The external links without the ones filled with an id the reader may not see, every marker removed"""
    kept: list[dict[str, Any]] = []

    for link in links or []:
        person_ids: list[int] = ids_of(link.pop(PersonRenderMarker.LINK_IDS.value, None))

        if all(object_id in visible for object_id in person_ids):
            kept.append(link)

    return kept


def reference_person_ids(reference: dict[str, Any]) -> set[int]:
    """
    The person ids a reference payload shows - in its summaries and in its marked line

    Args:
        reference (dict[str, Any]): A reference payload (``TypeReferenceKey``)

    Returns:
        set[int]: The ids to resolve
    """
    ids: set[int] = {
        object_id
        for entry in reference.get(TypeReferenceKey.SUMMARIES.value) or [] if _is_person_field(entry)
        for object_id in ids_of(entry.get(FieldKey.VALUE.value))
    }
    marker: dict[str, Any] = reference.get(PersonRenderMarker.LINE.value) or {}
    ids.update(object_id for value in marker.get(PersonLineMarkerKey.INPUTS.value) or [] if not isinstance(value, str)
               for object_id in ids_of(value))

    return ids


def apply_to_reference(reference: dict[str, Any], visible: Mapping[int, dict[str, Any]]) -> None:
    """
    Rewrites a reference payload's person summary values to their labels and fills its marked line again

    Args:
        reference (dict[str, Any]): A reference payload (changed in place; its marker removed)
        visible (Mapping[int, dict[str, Any]]): The selections the reader may see, by id
    """
    for entry in reference.get(TypeReferenceKey.SUMMARIES.value) or []:
        if _is_person_field(entry):
            entry[FieldKey.VALUE.value] = visible_labels_text(entry.get(FieldKey.VALUE.value), visible)

    marker: dict[str, Any] | None = reference.pop(PersonRenderMarker.LINE.value, None)

    if marker:
        reference[TypeReferenceKey.LINE.value] = marker[PersonLineMarkerKey.TEMPLATE.value].format(*[
            value if isinstance(value, str) else visible_labels_text(value, visible)
            for value in marker[PersonLineMarkerKey.INPUTS.value]
        ])


def summary_value(summary_field: dict[str, Any], stored_value: Any) -> Any:
    """
    The value a reference summary entry is built with: a person value raw - the person pass labels it - else as text

    Args:
        summary_field (dict[str, Any]): The summary field definition of the referenced Type
        stored_value (Any): The referenced object's stored value

    Returns:
        Any: The raw value of a person field, the text of any other
    """
    return stored_value if _is_person_field(summary_field) else str(stored_value)


def mark_reference_line(reference: dict[str, Any], template: str, summaries: list[dict[str, Any]]) -> None:
    """
    Marks a filled reference line whose summary values hold a person, so the person pass fills it again with labels

    Args:
        reference (dict[str, Any]): The reference payload (changed in place)
        template (str): The unfilled line
        summaries (list[dict[str, Any]]): The summary entries the line was filled with, in placeholder order
    """
    if any(_is_person_field(entry) for entry in summaries):
        reference[PersonRenderMarker.LINE.value] = {
            PersonLineMarkerKey.TEMPLATE.value: template,
            PersonLineMarkerKey.INPUTS.value: [entry.get(FieldKey.VALUE.value) for entry in summaries],
        }


def mark_link_person_ids(link: dict[str, Any], field_names: list[str], values: list[Any],
                         selectors: dict[str, dict[str, Any]]) -> None:
    """
    Marks an external link filled from a person selector with the ids it was filled with

    Args:
        link (dict[str, Any]): The serialised link (changed in place)
        field_names (list[str]): The fields the link's placeholders are filled from, in order
        values (list[Any]): Their values, in the same order
        selectors (dict[str, dict[str, Any]]): The person selectors of the object's Type, by name
    """
    person_values: list[Any] = [value for name, value in zip(field_names, values) if name in selectors]

    if person_values:
        link[PersonRenderMarker.LINK_IDS.value] = [object_id for value in person_values for object_id in ids_of(value)]

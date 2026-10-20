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
A CmdbType's copy of a global section template is the template's

A type that uses a global section template (``is_global``, the predefined ones included) lists the template's NAME
in ``global_template_ids`` and carries a section of the same name plus that section's field definitions. The copy
is the template's, not the type's: the frontend builder locks such a section, and every template change is
propagated over it wholesale (``SectionTemplatesManager._apply_template_changes_to_type``). So on every type write
- create, update and import - the copy is put back in line with the template instead of being stored as sent:

* the section takes the template's label, kind and field list (in the template's order), and the definition of
  each of those fields is the template's - a missing one is added, a rewritten one is replaced
* a claimed template the type carries no section for gets one, built from the template; a template field placed
  in another section is moved back into the template's (a layout change only - the field and its values stay)
* a claim naming no stored global template is dropped from ``global_template_ids``; whatever section and fields
  the type carries under that name stay, as the type's own data
* a field the template does not own, placed inside the template's section, is a CONFLICT the caller refuses: the
  section becomes exactly the template's, and silently pushing the field out would leave it in no section (and
  removing it would empty its value on every object)

``reconcile_type_with_global_templates`` is pure - it works on the type document and the templates handed to it -
so the routes and the import read the templates once (``resolve_global_templates``) and share it
"""
from copy import deepcopy
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any, NamedTuple

from cmdb.models.section_template_model import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

if TYPE_CHECKING:
    # The lookup needs nothing but the manager's find; keeping cmdb.manager out of the module-level imports keeps
    # this leaf free of the manager package (see predefined_section_guard)
    from cmdb.manager import SectionTemplatesManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


class TemplateSectionConflict(NamedTuple):
    """A field a global template does not own, found inside that template's section"""
    template_name: str
    field_name: str


class GlobalTemplateReconcile(NamedTuple):
    """
    What reconciling a type with its global templates found

    Attributes:
        conflicts (list[TemplateSectionConflict]): Foreign fields inside a template's section - the caller refuses
        dropped_claims (list[str]): Claims that name no stored global template, taken out of global_template_ids
    """
    conflicts: list[TemplateSectionConflict]
    dropped_claims: list[str]


def first_template_conflict(outcome: GlobalTemplateReconcile) -> tuple[str, list[str]] | None:
    """
    Names the first template whose section holds foreign fields, with those fields - what a refusal reports

    Args:
        outcome (GlobalTemplateReconcile): What the reconcile found

    Returns:
        tuple[str, list[str]] | None: (template name, its foreign field names sorted), or None without a conflict
    """
    if not outcome.conflicts:
        return None

    template_name: str = outcome.conflicts[0].template_name

    return template_name, sorted(
        conflict.field_name for conflict in outcome.conflicts if conflict.template_name == template_name
    )


def resolve_global_templates(
    section_templates_manager: 'SectionTemplatesManager',
    names: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Looks the given global section templates up in a single query

    Args:
        section_templates_manager (SectionTemplatesManager): Manager used to read the templates
        names (list[str]): The template names to resolve

    Raises:
        BaseManagerGetError: If the template lookup fails

    Returns:
        dict[str, dict[str, Any]]: The global templates that exist here, keyed by name
    """
    if not names:
        return {}

    templates = section_templates_manager.find({
        SectionTemplateKey.NAME.value: {'$in': sorted(set(names))},
        SectionTemplateKey.IS_GLOBAL.value: True,
    })

    return {
        template[SectionTemplateKey.NAME.value]: template
        for template in templates
        if template.get(SectionTemplateKey.NAME.value)
    }


def claimed_template_names(type_document: dict[str, Any]) -> list[str]:
    """
    The global template names a type document claims, each once, in the order given

    Args:
        type_document (dict[str, Any]): The type document

    Returns:
        list[str]: The claimed names (non-string entries are not names and are left out)
    """
    claims: Any = type_document.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value) or []

    if not isinstance(claims, list):
        return []

    return list(dict.fromkeys(name for name in claims if isinstance(name, str)))


def reconcile_type_with_global_templates(
    type_document: dict[str, Any],
    templates_by_name: dict[str, dict[str, Any]],
) -> GlobalTemplateReconcile:
    """
    Puts a type document's copies of its global templates back in line with the templates, in place

    See the module docstring for the rule. A conflict leaves the document partly reconciled; the caller refuses
    the write, so that state is never stored

    Args:
        type_document (dict[str, Any]): The type document about to be written, modified in place
        templates_by_name (dict[str, dict[str, Any]]): The stored global templates, keyed by name - at least the
            claimed ones that exist

    Returns:
        GlobalTemplateReconcile: The conflicts to refuse and the claims that were dropped
    """
    claims: list[str] = claimed_template_names(type_document)
    resolved: list[str] = [name for name in claims if name in templates_by_name]
    dropped: list[str] = [name for name in claims if name not in templates_by_name]

    if TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value in type_document:
        type_document[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] = resolved

    conflicts: list[TemplateSectionConflict] = []

    for template_name in resolved:
        conflicts.extend(_reconcile_one_template(type_document, templates_by_name[template_name]))

    return GlobalTemplateReconcile(conflicts=conflicts, dropped_claims=dropped)


def _reconcile_one_template(type_document: dict[str, Any], template: dict[str, Any]) -> list[TemplateSectionConflict]:
    """
    Puts the type's copy of one global template back in line with it, in place

    Args:
        type_document (dict[str, Any]): The type document, modified in place
        template (dict[str, Any]): The stored global template

    Returns:
        list[TemplateSectionConflict]: The foreign fields found inside the template's section
    """
    template_name: str = template[SectionTemplateKey.NAME.value]
    template_fields: list[dict[str, Any]] = [
        field for field in template.get(SectionTemplateKey.FIELDS.value) or []
        if isinstance(field, dict) and isinstance(field.get(FieldKey.NAME.value), str)
    ]
    template_field_names: list[str] = [field[FieldKey.NAME.value] for field in template_fields]

    _replace_field_definitions(type_document, template_fields)

    section: dict[str, Any] | None = _template_section(type_document, template_name)

    if section is None:
        return []

    # A section field list that is no list holds no field names to judge; it is replaced by the template's below
    listed: Any = section.get(SectionKey.FIELDS.value)
    conflicts: list[TemplateSectionConflict] = [
        TemplateSectionConflict(template_name, field_name)
        for field_name in (listed if isinstance(listed, list) else [])
        if field_name not in template_field_names
    ]

    _move_out_of_other_sections(type_document, section, set(template_field_names))

    section[SectionKey.TYPE.value] = template.get(SectionTemplateKey.TYPE.value, section.get(SectionKey.TYPE.value))
    section[SectionKey.LABEL.value] = template.get(SectionTemplateKey.LABEL.value, section.get(SectionKey.LABEL.value))
    section[SectionKey.FIELDS.value] = list(template_field_names)

    return conflicts


def _template_section(type_document: dict[str, Any], template_name: str) -> dict[str, Any] | None:
    """
    The type's section of a template, created (empty) at the end of the layout when the type carries none

    A ``render_meta`` that is no document is replaced; a ``sections`` value that is no list is left alone (the
    structure rules judge it), and then there is no section to reconcile

    Args:
        type_document (dict[str, Any]): The type document, modified in place when the section is created
        template_name (str): The template's name, which is the section's

    Returns:
        dict[str, Any] | None: The section, as it sits in the document, or None when the layout is unusable
    """
    render_meta: Any = type_document.get(TypeSchemaKey.RENDER_META.value)

    if not isinstance(render_meta, dict):
        render_meta = {}
        type_document[TypeSchemaKey.RENDER_META.value] = render_meta

    if TypeSchemaKey.SECTIONS.value not in render_meta or render_meta[TypeSchemaKey.SECTIONS.value] is None:
        render_meta[TypeSchemaKey.SECTIONS.value] = []

    sections: Any = render_meta[TypeSchemaKey.SECTIONS.value]

    if not isinstance(sections, list):
        return None

    for section in sections:
        if isinstance(section, dict) and section.get(SectionKey.NAME.value) == template_name:
            return section

    section = {SectionKey.NAME.value: template_name, SectionKey.FIELDS.value: []}
    sections.append(section)

    return section


def _move_out_of_other_sections(type_document: dict[str, Any], own_section: dict[str, Any], names: set[str]) -> None:
    """
    Takes a template's fields out of every section but the template's own, in place

    A template field belongs to the template's section; listed in a second one it would be shown twice and claimed
    twice. Only the layout changes - the field definition and the objects' values are untouched

    Args:
        type_document (dict[str, Any]): The type document, modified in place
        own_section (dict[str, Any]): The template's section, left alone
        names (set[str]): The template's field names
    """
    render_meta: Any = type_document.get(TypeSchemaKey.RENDER_META.value) or {}

    for section in render_meta.get(TypeSchemaKey.SECTIONS.value) or []:
        if section is own_section or not isinstance(section, dict):
            continue

        section_fields: Any = section.get(SectionKey.FIELDS.value)

        if isinstance(section_fields, list) and names.intersection(section_fields):
            section[SectionKey.FIELDS.value] = [name for name in section_fields if name not in names]


def _replace_field_definitions(type_document: dict[str, Any], template_fields: list[dict[str, Any]]) -> None:
    """
    Makes the template's field definitions the type's: a rewritten one replaced where it sits, a missing one added

    A ``fields`` value that is no list is left alone - the structure rules judge it

    Args:
        type_document (dict[str, Any]): The type document, modified in place
        template_fields (list[dict[str, Any]]): The template's field definitions
    """
    if type_document.get(TypeSchemaKey.FIELDS.value) is None:
        type_document[TypeSchemaKey.FIELDS.value] = []

    type_fields: Any = type_document[TypeSchemaKey.FIELDS.value]

    if not isinstance(type_fields, list):
        return

    by_name: dict[str, dict[str, Any]] = {field[FieldKey.NAME.value]: field for field in template_fields}
    seen: set[str] = set()

    for index, field in enumerate(type_fields):
        name: Any = field.get(FieldKey.NAME.value) if isinstance(field, dict) else None

        if name in by_name and name not in seen:
            type_fields[index] = deepcopy(by_name[name])
            seen.add(name)

    type_fields.extend(deepcopy(field) for name, field in by_name.items() if name not in seen)

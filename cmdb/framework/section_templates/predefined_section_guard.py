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
Identification of the CmdbType fields a predefined CmdbSectionTemplate owns

A predefined section template (``predefined: True``) is DataGerry-provided and immutable: the REST
routes refuse to create it, edit it or delete it. A CmdbType using such a template materializes a
copy of the template's section and its field definitions onto itself, and that copy has to stay in
lockstep with the template - ``SectionTemplatesManager._apply_template_changes_to_type`` replaces a
consuming type's template field definitions wholesale whenever the template changes, so any local
edit is silently reverted while the CmdbObjects that relied on it keep their values.

The one write path that edited such a field definition was the "extend a select field with a value
the type does not know yet" convenience of the object import and the object create / update routes:
an unknown value was appended to the select field's ``options``, including on a field belonging to a
predefined template. These helpers name the select fields that are off limits so those paths can
reject the unknown value instead.

The template name is the section name: a CmdbType lists the *names* of the global templates it uses
in ``global_template_ids`` (despite the plural 'ids') and carries one render_meta section of the same
name per template - the same pairing ``get_types_using_template`` and
``compute_removed_global_templates`` rely on.
"""
from logging import Logger, getLogger
from typing import TYPE_CHECKING

from cmdb.models.section_template_model import SectionTemplateKey
from cmdb.models.type_model import CmdbType, FieldType

if TYPE_CHECKING:
    # Imported for type checking only: the database lookup below needs nothing but the manager's
    # get_distinct, and keeping cmdb.manager out of the module-level imports lets the leaf helpers
    # (and their callers, e.g. the object import validator) stay free of the manager package
    from cmdb.manager import SectionTemplatesManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Reason appended to the rejection of a value that would extend a predefined template's select field.
# Formatted with the field name, the offending value and the owning template name
PREDEFINED_SELECT_OPTION_REJECTED: str = (
    "'{value}' is not an allowed option and it cannot be added because the field belongs to the "
    "predefined section template '{template}'"
)


def get_predefined_template_names(section_templates_manager: 'SectionTemplatesManager') -> set[str]:
    """
    Reads the names of every predefined CmdbSectionTemplate from the database

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates

    Returns:
        set[str]: Names of all templates flagged ``predefined``, empty when none exist
    """
    return set(
        section_templates_manager.get_distinct(
            SectionTemplateKey.NAME.value,
            {SectionTemplateKey.PREDEFINED.value: True},
        )
    )


def predefined_select_fields(
        type_instance: CmdbType,
        predefined_template_names: set[str],
    ) -> dict[str, str]:
    """
    Maps each of a type's select fields that a predefined section template owns to that template

    Walks the type's global templates, keeps the predefined ones and collects the select-typed fields
    of the matching render_meta section. A template the type references without carrying its section
    (an inconsistent type document) contributes nothing

    Args:
        type_instance (CmdbType): The type whose select fields are classified
        predefined_template_names (set[str]): Names of the predefined templates (see
            ``get_predefined_template_names``)

    Returns:
        dict[str, str]: {select field name: name of the predefined template owning it}
    """
    if not predefined_template_names:
        return {}

    select_field_names: set[str] = set(type_instance.get_all_fields_of_type(FieldType.SELECT.value))

    if not select_field_names:
        return {}

    owned_select_fields: dict[str, str] = {}

    for template_name in type_instance.global_template_ids or []:
        if template_name not in predefined_template_names:
            continue

        section = type_instance.get_section(template_name)

        if section is None:
            LOGGER.warning(
                "[predefined_select_fields] Type ID: %s references the predefined template '%s' "
                "without carrying its section", type_instance.public_id, template_name
            )
            continue

        for field_name in section.get_fields():
            if field_name in select_field_names:
                owned_select_fields[field_name] = template_name

    return owned_select_fields


def resolve_predefined_select_fields(
        type_instance: CmdbType,
        section_templates_manager: 'SectionTemplatesManager',
    ) -> dict[str, str]:
    """
    Resolves the predefined-template-owned select fields of a type, hitting the database only if needed

    A type that uses no global template at all cannot own such a field, so the template lookup is
    skipped entirely for it - the common case on the object write paths

    Args:
        type_instance (CmdbType): The type whose select fields are classified
        section_templates_manager (SectionTemplatesManager): db interface for section templates

    Returns:
        dict[str, str]: {select field name: name of the predefined template owning it}
    """
    if not type_instance.global_template_ids:
        return {}

    return predefined_select_fields(type_instance, get_predefined_template_names(section_templates_manager))

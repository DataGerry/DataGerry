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
The VIRTUAL section templates - definitions that look like a global template but are never stored

A virtual template exists so the frontend keeps the drag-and-drop experience of a global section
template for a feature that does not store its data on the CmdbObject at all. Dropping
``dg-virtual-tpl-ports`` onto a CmdbType is how a user says "this type has ports"; the frontend then
sends ``uses_ports: true`` in the type payload and the ports themselves live in framework.ports.

Four properties make it virtual, and each of them matters:

* **No public_id, never written to the database.** It is not in framework.sectionTemplates, so it does
  not appear in ``GET /section_templates/``, ``/<id>``, ``/<id>/count`` or the global-template usage
  count, and ``get_predefined_template_names`` never sees it - the predefined-select guard therefore
  never applies to its fields, which is intended: its select values are CmdbExtendableOptions, not
  type select fields. Note that this holds *despite* the ``predefined: True`` flag below: that guard
  resolves predefined template NAMES out of the collection, so a flag on a payload that was never
  stored cannot reach it.
* **Never merged into a CmdbType response.** DataGerry has no partial update, so anything a type GET
  returns is persisted by the next PUT: a type response carrying this section would inline it for
  real. ``dg-virtual-tpl-ports`` appearing in a type's ``global_template_ids`` is a bug, not a
  supported state.
* **Its fields are DERIVED from the port model's own constants**, so the template and the collection
  cannot drift. A port field added to ``PORT_TEMPLATE_FIELD_KEYS`` without a presentation spec here
  raises rather than silently disappearing from the UI.
* **Its selects carry ``option_type`` instead of an inline ``options`` list.** The values are
  CmdbExtendableOptions, so the frontend loads them by OptionType and extends them through the
  existing ``POST /rest/extendable_options/`` - no new route needed.

The ``dg-virtual-tpl-`` prefix is RESERVED on the section-template create route, so no stored template
can ever shadow a virtual one and the mechanism is reusable for a later feature
"""
from logging import Logger, getLogger
from typing import Any, NamedTuple

from cmdb.models.port_model import (
    PORT_SELECT_FIELD_OPTION_TYPES,
    PORT_TEMPLATE_FIELD_KEYS,
    PortKey,
)
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The reserved name prefix. Refused by the section-template create route, so a stored template can
# never shadow a virtual one
VIRTUAL_TEMPLATE_NAME_PREFIX: str = 'dg-virtual-tpl-'

# The Port Connectivity virtual template
PORTS_VIRTUAL_TEMPLATE_NAME: str = f'{VIRTUAL_TEMPLATE_NAME_PREFIX}ports'
PORTS_VIRTUAL_TEMPLATE_LABEL: str = 'Ports'


class VirtualFieldSpec(NamedTuple):
    """
    How one derived port field is presented in the virtual template

    Attributes:
        field_type (FieldType): The input the frontend renders
        label (str): The label shown next to it
    """
    field_type: FieldType
    label: str


# Presentation of every field in PORT_TEMPLATE_FIELD_KEYS. Deliberately a SEPARATE map from the port
# model's own constants: the model owns which fields exist and in which order, this owns how they look.
# A port field added there without an entry here raises in get_ports_virtual_template rather than
# quietly vanishing from the UI - which is the whole reason the fields are derived rather than restated
PORT_FIELD_PRESENTATION: dict[PortKey, VirtualFieldSpec] = {
    PortKey.NAME: VirtualFieldSpec(FieldType.TEXT, 'Name'),
    PortKey.PORT_NUMBER: VirtualFieldSpec(FieldType.NUMBER, 'Port Number'),
    PortKey.STATUS: VirtualFieldSpec(FieldType.SELECT, 'Status'),
    PortKey.PORT_TYPE: VirtualFieldSpec(FieldType.SELECT, 'Port Type'),
    PortKey.SPEED: VirtualFieldSpec(FieldType.SELECT, 'Speed'),
    PortKey.DESCRIPTION: VirtualFieldSpec(FieldType.TEXT, 'Description'),
}

# The one required field: a port is identified by its name within its face, and the create route
# refuses a blank one, so the form has to say so too
REQUIRED_PORT_FIELDS: frozenset[PortKey] = frozenset({PortKey.NAME})

# -------------------------------------------------------------------------------------------------------------------- #

def build_virtual_port_field(field_key: PortKey) -> dict[str, Any]:
    """
    Builds one field entry of the ports virtual template

    A select carries its OPTION_TYPE instead of an inline OPTIONS list, because its values are
    CmdbExtendableOptions the frontend loads (and extends) by OptionType

    Args:
        field_key (PortKey): The port field to present

    Raises:
        KeyError: If the field has no presentation spec - which is what makes a port field added to
            PORT_TEMPLATE_FIELD_KEYS without one a loud failure instead of a missing input

    Returns:
        dict[str, Any]: The field entry
    """
    spec: VirtualFieldSpec = PORT_FIELD_PRESENTATION[field_key]

    field: dict[str, Any] = {
        FieldKey.TYPE.value: spec.field_type.value,
        FieldKey.NAME.value: field_key.value,
        FieldKey.LABEL.value: spec.label,
    }

    if field_key in REQUIRED_PORT_FIELDS:
        field[FieldKey.REQUIRED.value] = True

    option_type = PORT_SELECT_FIELD_OPTION_TYPES.get(field_key)

    if option_type is not None:
        field[FieldKey.OPTION_TYPE.value] = option_type.value

    return field


def get_ports_virtual_template() -> dict[str, Any]:
    """
    Builds the ``dg-virtual-tpl-ports`` virtual section template

    Shaped like a stored predefined global section template so the frontend can render it with the
    machinery it already has - minus the one key a virtual template must not have: no ``public_id``,
    because it is not a resource and nothing can be fetched, updated or counted by id.

    ``predefined`` IS set: it is what tells the frontend the section is system-owned, so the type
    builder locks it the way it locks the shipped templates - no rename, no field editing, no delete.
    That is not a claim about propagation (a virtual template is never propagated into a CmdbType, and
    is never in the collection the seeding code writes) but about ownership, which is also exactly what
    the flag means on the stored routes: a predefined template is neither editable nor deletable

    Raises:
        KeyError: If a port field carries no presentation spec (see build_virtual_port_field)

    Returns:
        dict[str, Any]: The virtual section template
    """
    return {
        SectionTemplateKey.NAME.value: PORTS_VIRTUAL_TEMPLATE_NAME,
        SectionTemplateKey.LABEL.value: PORTS_VIRTUAL_TEMPLATE_LABEL,
        SectionTemplateKey.TYPE.value: SectionType.MDS_SECTION.value,
        SectionTemplateKey.IS_GLOBAL.value: True,
        SectionTemplateKey.PREDEFINED.value: True,
        SectionTemplateKey.FIELDS.value: [
            build_virtual_port_field(field_key) for field_key in PORT_TEMPLATE_FIELD_KEYS
        ],
    }


def get_virtual_section_templates() -> list[dict[str, Any]]:
    """
    Builds every virtual section template the backend offers

    One entry today. The route returns a list so a second virtual template needs no route change

    Returns:
        list[dict[str, Any]]: The virtual section templates
    """
    return [get_ports_virtual_template()]


def is_virtual_template_name(name: Any) -> bool:
    """
    Reports whether a name belongs to the reserved virtual-template space

    Used by the section-template create route to refuse it: a stored template carrying a virtual name
    would shadow the virtual one for every frontend that resolves templates by name

    Args:
        name (Any): The requested template name, as it came off the request

    Returns:
        bool: True when the name starts with the reserved prefix
    """
    return isinstance(name, str) and name.startswith(VIRTUAL_TEMPLATE_NAME_PREFIX)

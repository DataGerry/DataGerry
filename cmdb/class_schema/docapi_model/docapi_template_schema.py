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
Validation schema for DocapiTemplate

A DocapiTemplate is an HTML template rendered into a PDF for one CmdbObject (collection ``docapi.templates``).
This module is the single source of the document's Cerberus validation schema, consumed as DocapiTemplate.SCHEMA,
and the two write routes derive their request schemas from it (``build_write_schema``): the create route purges
``public_id`` and ``author_id``, which the server stamps, and the update route purges ``author_id``, which it keeps
from the stored template. The update addresses its template by the body's ``public_id``, so the key stays required
there.

Every rule is a TYPE rule the renderer depends on: a value of another type used to be stored and to fail every
later render of the template with a 500. Inside the five presentation blocks only the keys the renderer reads
are typed - each block accepts further keys - and every block, like every optional scalar, may be null, which
the model reads as its default
"""
from typing import Any, Callable
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801

def _check_template_name(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Cerberus `check_with` rule holding a template name to the naming rule

    A name is non-blank and carries no ``/``: the by-name route addresses a template by its name as one URL path
    segment, and the frontend's availability check is that route

    Args:
        field (str): The field being validated
        value (Any): Its value; a value that is no string is the type rule's to refuse
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.docapi.docapi_template.docapi_template_constants import (
        TEMPLATE_NAME_BLANK_MSG,
        TEMPLATE_NAME_FORBIDDEN_CHARACTER,
        TEMPLATE_NAME_SEPARATOR_MSG,
    )

    if not isinstance(value, str):
        return

    if not value.strip():
        error(field, TEMPLATE_NAME_BLANK_MSG)
    elif TEMPLATE_NAME_FORBIDDEN_CHARACTER in value:
        error(field, TEMPLATE_NAME_SEPARATOR_MSG)


def _block(schema: dict[str, Any]) -> dict[str, Any]:
    """
    The rule of a presentation block: an object or null, the renderer's keys typed, further keys allowed

    Args:
        schema (dict[str, Any]): The rules of the keys the renderer reads

    Returns:
        dict[str, Any]: The Cerberus rule
    """
    return {'type': 'dict', 'nullable': True, 'allow_unknown': True, 'schema': schema}


def _page_section_schema() -> dict[str, Any]:
    """
    The keys of a header or footer block: whether it is shown, its HTML, and its height in points

    Returns:
        dict[str, Any]: The Cerberus rules of the block's keys
    """
    return {
        'activated': {'type': 'boolean', 'nullable': True},
        'content': {'type': 'string', 'nullable': True},
        'config': _block({'height': {'type': 'number', 'nullable': True}}),
    }


def get_docapi_template_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a DocapiTemplate document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as DocapiTemplate.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own package is
    # still initialising (see class_schema/__init__.py)
    from cmdb.framework.docapi.docapi_template.docapi_template_constants import (
        DOCAPI_TEMPLATE_MARGIN_KEYS,
        TEMPLATE_NAME_MAX_LENGTH,
        DocapiTemplateKey,
    )
    from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType

    return {
        DocapiTemplateKey.PUBLIC_ID.value: {'type': 'integer', 'required': True},
        DocapiTemplateKey.NAME.value: {  # The template's unique, immutable handle
            'type': 'string',
            'required': True,
            'maxlength': TEMPLATE_NAME_MAX_LENGTH,
            'check_with': _check_template_name,
        },
        DocapiTemplateKey.LABEL.value: {'type': 'string', 'nullable': True},
        DocapiTemplateKey.DESCRIPTION.value: {'type': 'string', 'nullable': True},
        DocapiTemplateKey.ACTIVE.value: {'type': 'boolean', 'nullable': True},  # null reads as True
        DocapiTemplateKey.AUTHOR_ID.value: {'type': 'integer', 'nullable': True},
        DocapiTemplateKey.TEMPLATE_DATA.value: {'type': 'string', 'nullable': True},
        DocapiTemplateKey.TEMPLATE_STYLE.value: {'type': 'string', 'nullable': True},
        DocapiTemplateKey.TEMPLATE_TYPE.value: {  # null reads as OBJECT
            'type': 'string',
            'nullable': True,
            'allowed': [template_type.value for template_type in DocapiTemplateType],
        },
        DocapiTemplateKey.TEMPLATE_PARAMETERS.value: _block({'type': {'type': 'integer', 'nullable': True}}),
        DocapiTemplateKey.HEADER.value: _block(_page_section_schema()),
        DocapiTemplateKey.FOOTER.value: _block(_page_section_schema()),
        DocapiTemplateKey.TABLE_OF_CONTENTS.value: _block({
            'activated': {'type': 'boolean', 'nullable': True},
            'config': {'type': 'dict', 'nullable': True},
        }),
        DocapiTemplateKey.COVER_PAGE.value: _block({
            'activated': {'type': 'boolean', 'nullable': True},
            'content': {'type': 'string', 'nullable': True},
            'config': {'type': 'dict', 'nullable': True},
        }),
        DocapiTemplateKey.PAGE_CONFIG.value: _block({
            'margin': _block({key: {'type': 'number', 'nullable': True} for key in DOCAPI_TEMPLATE_MARGIN_KEYS}),
        }),
    }

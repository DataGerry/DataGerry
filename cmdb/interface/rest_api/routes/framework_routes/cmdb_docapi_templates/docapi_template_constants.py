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
Shared constants for the DocapiTemplate REST routes

Names the ACL rights guarding the DocapiTemplate routes so the routes reference enum members
instead of repeating the literal right strings, the media type and file extension the render
route answers a rendered document with, and the document keys a searchfilter may match on.
"""
from cmdb.utils import BaseStrEnum
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RENDER_OBJECT_RIGHT',
    'RENDERED_DOCUMENT_MIMETYPE',
    'RENDERED_DOCUMENT_EXTENSION',
    'SEARCHFILTER_KEYS',
    'SEARCHFILTER_NESTED_KEYS',
    'DocapiTemplateRight',
]

# What the render route answers with. A DocapiTemplate is HTML, but it is rendered to PDF before it
# leaves the route, so the media type and the extension of the download are both fixed here
RENDERED_DOCUMENT_MIMETYPE: str = 'application/pdf'
RENDERED_DOCUMENT_EXTENSION: str = 'pdf'

# The keys a `GET /docapi/template/by/<searchfilter>` filter may name. The filter reaches MongoDB as the
# query document itself, so it is limited to equality matches on these keys - an operator key such as
# `$where` or `$expr` would otherwise run server-side JavaScript. The template body keys (the HTML,
# the style and the page layout) are not searchable
SEARCHFILTER_KEYS: frozenset[str] = frozenset({
    DocapiTemplateKey.PUBLIC_ID.value,
    DocapiTemplateKey.NAME.value,
    DocapiTemplateKey.LABEL.value,
    DocapiTemplateKey.ACTIVE.value,
    DocapiTemplateKey.AUTHOR_ID.value,
    DocapiTemplateKey.TEMPLATE_TYPE.value,
    DocapiTemplateKey.TEMPLATE_PARAMETERS.value,
})

# The one searchfilter key whose value may be an object rather than a scalar: the frontend's document
# picker asks for `{"template_parameters": {"type": <type_id>}}`
SEARCHFILTER_NESTED_KEYS: frozenset[str] = frozenset({DocapiTemplateKey.TEMPLATE_PARAMETERS.value})

RENDER_OBJECT_RIGHT: str = 'base.framework.object.view'
"""
The right guarding the render route - a CmdbObject right, not a DocapiTemplate one

Rendering reads the target CmdbObject and puts its field values into the document, so the right that
decides it belongs to the object domain. The consequence is deliberate but worth knowing: holding all
four DocapiTemplate rights is not enough to render, and holding this right alone is
"""


class DocapiTemplateRight(BaseStrEnum):
    """
    ACL right identifiers guarding the DocapiTemplate REST routes
    """
    ADD = 'base.docapi.template.add'
    VIEW = 'base.docapi.template.view'
    EDIT = 'base.docapi.template.edit'
    DELETE = 'base.docapi.template.delete'

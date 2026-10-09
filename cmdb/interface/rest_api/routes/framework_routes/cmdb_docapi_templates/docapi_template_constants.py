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
from cmdb.models.right_model.right_constants import ObjectRightName
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

RENDER_OBJECT_RIGHT: str = ObjectRightName.VIEW.value
"""
The object half of the two rights guarding the render route

A render reads two things and answers both: the template, in full, and the target CmdbObject's field
values. So it requires the right of each - this one for the object, and `DocapiTemplateRight.VIEW` for the
template. Holding either alone is not enough
"""


#: What the render route answers for a template whose `active` flag is off
RENDER_TEMPLATE_DEACTIVATED_MSG: str = 'The Template with ID: {public_id} is deactivated and can not be rendered!'


#: What the render route answers a caller whose group may not READ the object's type
RENDER_OBJECT_DENIED_MSG: str = 'No permission to render the Object with ID: {object_id}!'


class DocapiTemplateRight(BaseStrEnum):
    """
    ACL right identifiers guarding the DocapiTemplate REST routes
    """
    ADD = 'base.docapi.template.add'
    VIEW = 'base.docapi.template.view'
    EDIT = 'base.docapi.template.edit'
    DELETE = 'base.docapi.template.delete'

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
Constants of the DocAPI PDF conversion: which resources a document may load
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ALLOWED_RESOURCE_PREFIX',
    'REFUSED_RESOURCE_URI',
]

# The one kind of resource a document may load: inline data, carried in the template itself - the form the template
# editor stores a picked image in. Compared case-sensitively, exactly as xhtml2pdf recognises an inline URI
ALLOWED_RESOURCE_PREFIX: str = 'data:'

# What a refused resource is replaced with: a well-formed inline URI holding nothing, so the conversion leaves the
# resource out instead of failing. xhtml2pdf falls back to the ORIGINAL uri when the callback answers a falsy value,
# so the refusal has to be a real, empty resource
REFUSED_RESOURCE_URI: str = 'data:text/plain;base64,'

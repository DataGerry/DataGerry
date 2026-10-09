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
The ``Content-Disposition`` value of every download the REST API answers

An HTTP header travels as latin-1 bytes - gunicorn writes it with ``.encode('latin-1')`` and refuses one it cannot
encode, closing the connection without an answer. A filename is free text, so it is carried twice:

* ``filename="..."`` - an ASCII fallback every client understands: the name with its accents stripped, characters
  ASCII cannot spell dropped, control characters removed and quotes escaped
* ``filename*=UTF-8''...`` - the exact name, percent-encoded (RFC 5987 / RFC 6266), which every current browser and
  the frontend's own parsers prefer

The second part is added only when the first is not the name itself, so a plain ASCII name answers exactly
``attachment; filename="<name>"``
"""
import re
import unicodedata
from urllib.parse import quote
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['CONTENT_DISPOSITION_HEADER', 'attachment_disposition']

CONTENT_DISPOSITION_HEADER: str = 'Content-Disposition'

ATTACHMENT_DISPOSITION_TYPE: str = 'attachment'

# The ASCII fallback when nothing of the name survives the reduction to ASCII (a name in Cyrillic, say)
FALLBACK_FILENAME_STEM: str = 'download'

# Characters RFC 5987 lets an ext-value carry as they are, beyond the letters, digits and '-._~' quote() keeps
RFC5987_ATTR_CHARS: str = "!#$&+^`|"

UTF8_CHARSET_PREFIX: str = "UTF-8''"
EXTENSION_SEPARATOR: str = '.'
NFKD_FORM: str = 'NFKD'
ASCII_ENCODING: str = 'ascii'

# What a quoted-string cannot carry: the C0 controls and DEL
CONTROL_CHARACTERS_PATTERN: re.Pattern[str] = re.compile(r'[\x00-\x1f\x7f]')


def _ascii_fallback(filename: str) -> str:
    """
    Reduces a filename to what a quoted ASCII header parameter can carry

    Args:
        filename (str): The filename as stored

    Returns:
        str: The ASCII fallback, quotes and backslashes escaped; ``download<.ext>`` when no stem survives
    """
    ascii_name: str = (
        unicodedata.normalize(NFKD_FORM, filename).encode(ASCII_ENCODING, 'ignore').decode(ASCII_ENCODING)
    )
    ascii_name = CONTROL_CHARACTERS_PATTERN.sub('', ascii_name)

    stem, separator, extension = ascii_name.rpartition(EXTENSION_SEPARATOR)

    if not separator:
        stem, extension = ascii_name, ''

    if not stem.strip():
        ascii_name = f'{FALLBACK_FILENAME_STEM}{separator}{extension}' if extension else FALLBACK_FILENAME_STEM

    return ascii_name.replace('\\', '\\\\').replace('"', '\\"')


def attachment_disposition(filename: str) -> str:
    """
    Builds the ``Content-Disposition`` value that hands a client a file to save under ``filename``

    Every value it answers is latin-1 - in fact ASCII - so no server can refuse the header. An ASCII name is
    answered as ``attachment; filename="<name>"``; any other name adds its exact UTF-8 spelling as ``filename*``

    Args:
        filename (str): The name the client should save the file under

    Returns:
        str: The header value
    """
    fallback: str = _ascii_fallback(filename)
    value: str = f'{ATTACHMENT_DISPOSITION_TYPE}; filename="{fallback}"'

    if fallback != filename:
        value += f'; filename*={UTF8_CHARSET_PREFIX}{quote(filename, safe=RFC5987_ATTR_CHARS)}'

    return value

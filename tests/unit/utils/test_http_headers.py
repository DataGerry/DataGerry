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
Unit tests for cmdb.utils.http_headers.attachment_disposition

Two properties carry the whole contract: whatever the name, the value is one gunicorn sends (it checks every header
value against its own ``HEADER_VALUE_RE`` and refuses one that fails), and the exact name can be read back out of it.
An ASCII name keeps the exact value every download answered before
"""
import re
from urllib.parse import unquote

import pytest
from gunicorn.http.wsgi import HEADER_VALUE_RE

from cmdb.utils import CONTENT_DISPOSITION_HEADER, attachment_disposition
# -------------------------------------------------------------------------------------------------------------------- #

NAMES: list[str] = [
    'report.txt', 'Отчёт.txt', 'Grüße.txt', '日本語.pdf', 'Ελληνικά.docx', 'łódź.csv', '€uro.xlsx', '📎',
    'no-extension', 'a"quoted".txt', 'back\\slash.txt', 'semi;colon.txt', 'line\nbreak.txt', ' spaced name .txt',
]

# The parameters of a value, read the way the frontend's own parsers read them
EXACT_NAME_PATTERN: re.Pattern[str] = re.compile(r"filename\*=UTF-8''([^;]+)")
FALLBACK_NAME_PATTERN: re.Pattern[str] = re.compile(r'filename="((?:[^"\\]|\\.)*)"')


def _fallback(value: str) -> str:
    """The quoted ASCII fallback, unescaped."""
    return re.sub(r'\\(.)', r'\1', FALLBACK_NAME_PATTERN.search(value).group(1))


def test_the_header_name() -> None:
    """One spelling for every route"""
    assert CONTENT_DISPOSITION_HEADER == 'Content-Disposition'


@pytest.mark.parametrize('filename', NAMES)
def test_every_value_is_one_gunicorn_sends(filename: str) -> None:
    """ASCII only, and accepted by the server's own header check"""
    value = attachment_disposition(filename)

    assert value.isascii()
    assert HEADER_VALUE_RE.fullmatch(value)


@pytest.mark.parametrize('filename', [name for name in NAMES if not name.isascii() or '"' in name or '\\' in name])
def test_a_name_that_is_not_plain_ascii_reads_back_exactly(filename: str) -> None:
    """``filename*`` decodes to the stored name, every character of it"""
    match = EXACT_NAME_PATTERN.search(attachment_disposition(filename))

    assert match
    assert unquote(match.group(1)) == filename


@pytest.mark.parametrize('filename', ['report.txt', '2026_10_08-objects.csv', 'activation_request.txt'])
def test_an_ascii_name_answers_exactly_as_before(filename: str) -> None:
    """No second parameter, the name quoted - byte for byte what the downloads answered"""
    assert attachment_disposition(filename) == f'attachment; filename="{filename}"'


@pytest.mark.parametrize(('filename', 'fallback'), [
    ('Grüße.txt', 'Grue.txt'),
    ('Отчёт.txt', 'download.txt'),
    ('📎', 'download'),
    ('a"quoted".txt', 'a"quoted".txt'),
    ('line\nbreak.txt', 'linebreak.txt'),
])
def test_the_ascii_fallback(filename: str, fallback: str) -> None:
    """Accents stripped, unspellable characters dropped, controls removed - and a stem when nothing is left"""
    assert _fallback(attachment_disposition(filename)) == fallback


def test_a_quote_cannot_close_the_fallback_early() -> None:
    """The quote is escaped, so the parameter ends where it should"""
    value = attachment_disposition('a"; filename="evil.exe')

    assert _fallback(value) == 'a"; filename="evil.exe'
    assert unquote(EXACT_NAME_PATTERN.search(value).group(1)) == 'a"; filename="evil.exe'

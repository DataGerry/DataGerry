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
Tripwire: every download's ``Content-Disposition`` is built by ``cmdb.utils.attachment_disposition``

A header is sent as latin-1, and a filename written into one bare - a media file named in Cyrillic, say - made the
server drop the connection without an answer. The helper carries any name safely, so the rule is that nothing else
in ``cmdb/`` spells the header: no string literal naming it and no hand-built ``attachment; ...`` value outside
``cmdb/utils/http_headers.py``.

Read with ``ast`` over every module under ``cmdb/``; docstrings are not code and are left out.
"""
import ast
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'
HELPER_MODULE: Path = CMDB_ROOT / 'utils' / 'http_headers.py'

HEADER_NAME: str = 'content-disposition'
DISPOSITION_PREFIX: str = 'attachment;'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The ids of every bare string statement - docstrings and their kin - which are prose, not code."""
    return {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def hand_built_dispositions(source: str) -> list[int]:
    """
    The lines of a module that spell the header or build its value by hand

    Args:
        source (str): A module's source

    Returns:
        list[int]: Line numbers of every string literal naming ``Content-Disposition`` or starting an
            ``attachment;`` value, f-strings included
    """
    tree = ast.parse(source)
    prose: set[int] = _docstring_nodes(tree)
    found: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in prose:
            continue

        text: str = node.value.strip().lower()

        if text == HEADER_NAME or text.startswith(DISPOSITION_PREFIX):
            found.append(node.lineno)

    return sorted(set(found))


def test_no_module_builds_the_header_by_hand() -> None:
    """Names each offending line"""
    modules: list[Path] = sorted(path for path in CMDB_ROOT.rglob('*.py') if path != HELPER_MODULE)
    offenders: list[str] = [
        f'{path.relative_to(CMDB_ROOT.parent)}:{line}'
        for path in modules
        for line in hand_built_dispositions(path.read_text(encoding='utf-8'))
    ]

    assert len(modules) >= MIN_SCANNED_MODULES
    assert not offenders, 'use cmdb.utils.CONTENT_DISPOSITION_HEADER / attachment_disposition: ' + ', '.join(offenders)


def test_the_check_sees_a_hand_built_header() -> None:
    """The checker itself: the name, a value, an f-string value - and never a docstring"""
    source = (
        '"""Mentions the Content-Disposition header in prose"""\n'
        "A = {'Content-Disposition': 'x'}\n"
        "B = f'attachment; filename=\"{name}\"'\n"
        "C = 'inline'\n"
    )

    assert hand_built_dispositions(source) == [2, 3]

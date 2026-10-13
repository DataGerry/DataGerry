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
Tripwire: every HTML-to-PDF conversion passes the resource policy

The HTML a DocAPI document is converted from is author-controlled, and xhtml2pdf on its own fetches every URL and
reads every path that HTML names. ``pdf_document_type.pdf_resource_link_callback`` is what keeps a conversion inside
the document; this scan fails on any ``CreatePDF`` / ``pisaDocument`` call under ``cmdb/`` that does not pass it as
``link_callback``, so a second conversion cannot slip in without it.

Read with ``ast`` over every module under ``cmdb/``.
"""
import ast
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'

CONVERSION_CALLS: frozenset[str] = frozenset({'CreatePDF', 'pisaDocument'})
CALLBACK_KEYWORD: str = 'link_callback'
POLICY_NAME: str = 'pdf_resource_link_callback'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000


def conversions(source: str) -> list[tuple[int, bool]]:
    """
    Every PDF conversion call of a module, and whether it passes the resource policy

    Args:
        source (str): A module's source

    Returns:
        list[tuple[int, bool]]: (line, passes ``link_callback=pdf_resource_link_callback``) per call
    """
    found: list[tuple[int, bool]] = []

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue

        name: str | None = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)

        if name in CONVERSION_CALLS:
            found.append((node.lineno, any(
                keyword.arg == CALLBACK_KEYWORD and isinstance(keyword.value, ast.Name)
                and keyword.value.id == POLICY_NAME
                for keyword in node.keywords
            )))

    return found


def _modules() -> list[Path]:
    """Every module under cmdb/"""
    return sorted(CMDB_ROOT.rglob('*.py'))


def test_the_scan_covers_the_tree() -> None:
    """A moved package must not make the scan pass vacuously"""
    assert len(_modules()) >= MIN_SCANNED_MODULES


def test_there_is_a_conversion_to_guard() -> None:
    """The one conversion is found - a renamed call would otherwise pass the next test vacuously"""
    assert any(conversions(path.read_text(encoding='utf-8')) for path in _modules())


def test_every_conversion_passes_the_resource_policy() -> None:
    """No CreatePDF / pisaDocument without link_callback=pdf_resource_link_callback"""
    unguarded: list[str] = [
        f'{path.relative_to(CMDB_ROOT.parent)}:{line}'
        for path in _modules()
        for line, guarded in conversions(path.read_text(encoding='utf-8'))
        if not guarded
    ]

    assert not unguarded



def test_the_scan_sees_a_missing_callback() -> None:
    """The detector itself: a bare call and a wrong callback are unguarded, the policy is guarded"""
    source: str = (
        "pisa.CreatePDF(html, dest=out)\n"
        "pisa.CreatePDF(html, dest=out, link_callback=other)\n"
        "pisaDocument(html, link_callback=pdf_resource_link_callback)\n"
    )

    assert conversions(source) == [(1, False), (2, False), (3, True)]

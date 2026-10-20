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
Tripwire: a pylint pragma names its messages symbolically, never by numeric id

``# pylint: disable=too-many-arguments`` and ``# pylint: disable=R0913`` suppress the same message, and a reader
grepping for one form finds only the sites written in it. The symbolic name is the spelling: it says what is waived.
``.pylintrc`` disables ``use-symbolic-message-instead``, so nothing else catches a numeric id.

Read from the comment tokens of every module under ``cmdb/`` and ``tests/``, so a string that merely looks like a
pragma is not mistaken for one. That a waiver is still NEEDED is pylint's own check: CI fails on
``useless-suppression``.
"""
import io
import re
import tokenize
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCANNED_ROOTS: list[Path] = [REPO_ROOT / 'cmdb', REPO_ROOT / 'tests']

# A pylint control comment, and a numeric message id inside one (C0114, R0913, W0613, ...)
PRAGMA_PATTERN: re.Pattern[str] = re.compile(r'pylint:\s*(disable|enable|disable-next)\s*=(?P<messages>.*)')
NUMERIC_ID_PATTERN: re.Pattern[str] = re.compile(r'\b[CRWEFI]\d{4}\b')

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 2000
MIN_PRAGMAS: int = 100


def numeric_pragmas(source: str) -> list[tuple[int, str]]:
    """
    The pylint pragmas of a module that name a message by its numeric id

    Args:
        source (str): A module's source

    Returns:
        list[tuple[int, str]]: (line, comment) of every such pragma
    """
    found: list[tuple[int, str]] = []

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue

        match = PRAGMA_PATTERN.search(token.string)

        if match and NUMERIC_ID_PATTERN.search(match.group('messages')):
            found.append((token.start[0], token.string))

    return found


def _count_pragmas(source: str) -> int:
    """How many pylint control comments the module holds."""
    return sum(
        1 for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and PRAGMA_PATTERN.search(token.string)
    )


def _modules() -> list[Path]:
    """Every Python module under the scanned roots."""
    return [path for root in SCANNED_ROOTS for path in sorted(root.rglob('*.py'))]


def test_the_scan_covers_the_tree() -> None:
    """Guards the scan itself"""
    modules = _modules()

    assert len(modules) >= MIN_SCANNED_MODULES
    assert sum(_count_pragmas(path.read_text(encoding='utf-8')) for path in modules) >= MIN_PRAGMAS


def test_no_pragma_names_a_message_by_number() -> None:
    """Names every numeric pragma, by file and line"""
    offenders: list[str] = [
        f'{path.relative_to(REPO_ROOT)}:{line}: {comment}'
        for path in _modules()
        for line, comment in numeric_pragmas(path.read_text(encoding='utf-8'))
    ]

    assert not offenders, 'spell the message symbolically:\n' + '\n'.join(offenders)


def test_the_check_sees_a_numeric_id_and_only_in_a_pragma() -> None:
    """The checker itself"""
    source = (
        'def f():  # pylint: disable=R0913, too-many-locals\n'
        '    pass\n'
        '# pylint: disable=too-many-arguments\n'
        'TEXT = "pylint: disable=R0913"\n'
        '# R0913 in a plain comment\n'
    )

    assert [line for line, _ in numeric_pragmas(source)] == [1]

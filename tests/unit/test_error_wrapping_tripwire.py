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
Tripwire: a wrapped error carries the exception it wraps, never only its text

``raise XxxError(str(err)) from err`` keeps the traceback (``__cause__``) but makes the wrapper's
``args[0]`` a string, so a caller that catches it sees ``'E11000 duplicate key error ...'`` instead of
an error it could branch on by type. ``raise XxxError(err) from err`` reads the same through ``str()``
and keeps the error. The shape is copied from the file next door, which is why this is a scan of the
whole ``cmdb/`` tree and not a one-off sweep.

What the scan deliberately leaves alone: a message that ADDS context around the error
(``XxxError(f"Bulk write failed in collection '{name}': {err}")``) or turns it into user-facing text
(``AuthenticationError(LdapAuthMessage.X.format(detail=err))``). Those say more than the error does;
a bare ``str(err)`` only ever says less.

Read with ``ast``, so every module is covered whether or not a test imports it.
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'

STR_BUILTIN: str = 'str'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000
MIN_WRAPPING_RAISES: int = 250


def _is_str_of(node: ast.expr, name: str) -> bool:
    """`str(<name>)` and nothing else."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == STR_BUILTIN
        and len(node.args) == 1 and not node.keywords
        and isinstance(node.args[0], ast.Name) and node.args[0].id == name
    )


def find_stringified_wraps(source: str) -> list[int]:
    """
    The lines that raise a new error from the caught one's bare text

    Args:
        source (str): A module's source

    Returns:
        list[int]: Line numbers of every ``raise X(str(<caught>))`` inside an ``except ... as <caught>``,
            whether the text is passed positionally or by keyword
    """
    found: list[int] = []

    for handler in ast.walk(ast.parse(source)):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue

        for node in ast.walk(handler):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                arguments = [*node.exc.args, *(keyword.value for keyword in node.exc.keywords)]

                if any(_is_str_of(argument, handler.name) for argument in arguments):
                    found.append(node.lineno)

    return found


def count_wrapping_raises(source: str) -> int:
    """
    How many raises inside an ``except ... as <caught>`` hand the caught error to the new one

    Args:
        source (str): A module's source

    Returns:
        int: Raises whose call names the caught error in any argument
    """
    count: int = 0

    for handler in ast.walk(ast.parse(source)):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue

        for node in ast.walk(handler):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                if any(isinstance(n, ast.Name) and n.id == handler.name for n in ast.walk(node.exc)):
                    count += 1

    return count


MODULES: list[Path] = sorted(CMDB_ROOT.rglob('*.py'))


class TestTheDetector:
    """The scan's own rule, pinned on snippets - a detector that finds nothing passes every module."""

    @pytest.mark.parametrize('snippet', [
        "try:\n    pass\nexcept Exception as err:\n    raise ValueError(str(err)) from err\n",
        "try:\n    pass\nexcept KeyError as e:\n    raise ValueError(str(e))\n",
        "try:\n    pass\nexcept Exception as err:\n    raise ValueError(message=str(err)) from err\n",
        "try:\n    pass\nexcept Exception as err:\n    raise error_class(str(err)) from err\n",
    ], ids=['positional', 'other-name-no-from', 'keyword', 'class-in-a-variable'])
    def test_a_stringified_wrap_is_found(self, snippet: str) -> None:
        """Every spelling that hands over only the text."""
        assert find_stringified_wraps(snippet) == [4]

    @pytest.mark.parametrize('snippet', [
        "try:\n    pass\nexcept Exception as err:\n    raise ValueError(err) from err\n",
        "try:\n    pass\nexcept Exception as err:\n    raise ValueError(f'while doing X: {err}') from err\n",
        "try:\n    pass\nexcept Exception as err:\n    raise ValueError(str(other)) from err\n",
        "try:\n    pass\nexcept Exception:\n    raise ValueError('fixed')\n",
        "def f(err):\n    raise ValueError(str(err))\n",
    ], ids=['the-exception', 'context-f-string', 'another-value', 'unnamed-handler', 'outside-a-handler'])
    def test_what_the_rule_leaves_alone(self, snippet: str) -> None:
        """The exception itself, added context, and anything that is not the caught error."""
        assert not find_stringified_wraps(snippet)


def test_the_scan_covers_the_tree() -> None:
    """Guards the census itself: the tree is there and it does wrap errors."""
    assert len(MODULES) > MIN_SCANNED_MODULES
    assert sum(count_wrapping_raises(path.read_text(encoding='utf-8')) for path in MODULES) > MIN_WRAPPING_RAISES


def test_no_module_wraps_an_error_as_its_text() -> None:
    """Every wrapped error in cmdb/ carries the exception: `XxxError(err) from err`."""
    offenders: list[str] = [
        f'{path.relative_to(CMDB_ROOT.parent)}:{line}'
        for path in MODULES
        for line in find_stringified_wraps(path.read_text(encoding='utf-8'))
    ]

    assert not offenders, f'raise XxxError(err) from err, not str(err): {offenders}'

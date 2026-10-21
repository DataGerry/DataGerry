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
Tripwire: three spacing rules flake8 reports but CI does not gate are held at zero under ``cmdb/``

flake8 runs in CI with ``--exit-zero``, so its findings are information only and a rule the tree once met drifts
back. These three were brought to zero and are kept there:

* ``E251`` - spaces around a keyword argument's ``=`` (``f(name = value)``; ``name: int = 1`` in a signature is fine)
* ``E261`` - fewer than two spaces before an inline comment
* ``E203`` - whitespace before ``,`` ``;`` or ``:`` (a list written with leading commas included)

Read with ``pycodestyle`` (pinned in ``requirements.txt``, the checker flake8 runs for these codes) in-process, so
the test needs no flake8 executable. The fix for a hit is the formatting the message names; nothing here is waived.
"""
from pathlib import Path

import pycodestyle
import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCANNED_ROOT: Path = REPO_ROOT / 'cmdb'
HELD_CODES: tuple[str, ...] = ('E251', 'E261', 'E203')
MAX_LINE_LENGTH: int = 120

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000


class _CollectingReport(pycodestyle.BaseReport):
    """A pycodestyle report that keeps every finding instead of printing it."""

    def __init__(self, options: object) -> None:
        super().__init__(options)
        self.findings: list[str] = []

    def error(self, line_number: int, offset: int, text: str, check: object) -> str | None:
        code: str | None = super().error(line_number, offset, text, check)

        if code:
            self.findings.append(f'{self.filename}:{line_number}:{offset + 1}: {text}')

        return code


def spacing_findings(paths: list[Path]) -> tuple[list[str], int]:
    """
    Runs the held spacing rules over the given modules

    Args:
        paths (list[Path]): The modules to check

    Returns:
        tuple[list[str], int]: Every finding as ``path:line:col: message``, and how many modules were checked
    """
    style = pycodestyle.StyleGuide(select=list(HELD_CODES), max_line_length=MAX_LINE_LENGTH, quiet=True)
    report = _CollectingReport(style.options)
    style.init_report(lambda _options: report)
    style.check_files([str(path) for path in paths])

    return report.findings, report.counters.get('files', 0)


def test_the_tree_holds_the_spacing_rules() -> None:
    """Every module under cmdb/ - no finding of E251, E261 or E203"""
    modules: list[Path] = sorted(SCANNED_ROOT.rglob('*.py'))
    findings, scanned = spacing_findings(modules)

    assert scanned >= MIN_SCANNED_MODULES
    assert not findings, '\n'.join(findings)


@pytest.mark.parametrize('code, source', [
    ('E251', 'value = dict(name = 1)\n'),
    ('E261', 'value = 1 # comment\n'),
    ('E203', 'value = [1 , 2]\n'),
])
def test_the_scan_reports_each_held_rule(tmp_path: Path, code: str, source: str) -> None:
    """The scan is not vacuous: a module breaking one rule is reported under that rule's code"""
    module: Path = tmp_path / 'module.py'
    module.write_text(source, encoding='utf-8')

    findings, scanned = spacing_findings([module])

    assert scanned == 1
    # E251 is reported once per side of the '=', so the codes are compared as a set
    assert {finding.split(': ', 1)[1].split()[0] for finding in findings} == {code}


@pytest.mark.parametrize('source', [
    'def f(name: int = 1) -> int:\n    return name\n',
    'value = 1  # comment\n',
    'value = [1, 2]\n',
])
def test_the_allowed_spellings_pass(tmp_path: Path, source: str) -> None:
    """An annotated default, a two-space comment and a plain list are not findings"""
    module: Path = tmp_path / 'module.py'
    module.write_text(source, encoding='utf-8')

    assert not spacing_findings([module])[0]

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
Tripwire: no test stubs a Service Portal answer with a top-level ``database``

The portal names a tenant database only inside each entry of ``subscriptions``. A stub that also put one at the top
level made a code path that read it pass every test while it failed against the real portal on every request.
``tests.utils.service_portal_answers`` builds both answers in the portal's own shape; this scan keeps a hand-written
dict from bringing the field back. A dict literal is a portal answer when it carries ``subscriptions``.

Read with ``ast`` over every module under ``tests/``.
"""
import ast
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

TESTS_ROOT: Path = Path(__file__).resolve().parents[1]

SUBSCRIPTIONS_KEY: str = 'subscriptions'
INVENTED_KEY: str = 'database'

# The smallest population the scan must still find, so a moved folder cannot make it pass vacuously
MIN_PORTAL_ANSWERS: int = 30


def portal_answers_with_a_top_level_database(source: str) -> tuple[int, list[int]]:
    """
    Scans a module's dict literals for portal answers

    Args:
        source (str): A module's source

    Returns:
        tuple[int, list[int]]: How many portal answers the module holds, and the lines of those naming a top-level
            ``database``
    """
    answers: int = 0
    offending: list[int] = []

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue

        keys = {key.value for key in node.keys if isinstance(key, ast.Constant)}

        if SUBSCRIPTIONS_KEY in keys:
            answers += 1

            if INVENTED_KEY in keys:
                offending.append(node.lineno)

    return answers, offending


def test_no_portal_stub_names_a_top_level_database() -> None:
    """Names each offending stub by file and line"""
    total: int = 0
    offenders: list[str] = []

    for path in sorted(TESTS_ROOT.rglob('*.py')):
        answers, offending = portal_answers_with_a_top_level_database(path.read_text(encoding='utf-8'))
        total += answers
        offenders += [f'{path.relative_to(TESTS_ROOT)}:{line}' for line in offending]

    assert total >= MIN_PORTAL_ANSWERS
    assert not offenders, 'build the answer with tests.utils.service_portal_answers: ' + ', '.join(offenders)


def test_the_check_sees_the_invented_field() -> None:
    """The checker itself: only a dict carrying subscriptions is an answer, and only its top level counts"""
    source = (
        "A = {'database': 'db', 'subscriptions': []}\n"
        "B = {'subscriptions': [{'database': 'db'}]}\n"
        "C = {'database': 'db'}\n"
    )

    assert portal_answers_with_a_top_level_database(source) == (2, [1])

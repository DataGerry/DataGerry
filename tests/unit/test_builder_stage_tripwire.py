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
Tripwire: an aggregation stage is built with its `Builder` constructor, never as a hand-written dict

`cmdb.manager.query_builder.builder.Builder` is the one place a stage's shape is written down. A
hand-written `{'$lookup': {...}}` works until it drifts from the constructor's shape - the argument order
of a `$lookup` and the options default of a `$regex` are where that has happened. This scan fails on a
single-key dict whose key is a stage that HAS a constructor, standing where a pipeline stage stands:

* an element of a list literal (a pipeline, a `$facet` branch, a `$lookup` sub-pipeline),
* the argument of `.append` / `.add_pipe` / `.insert`,
* a `return` value.

What it deliberately leaves alone:

* `builder.py` itself - the constructors are the dicts.
* The database updaters (`cmdb/database/updater/versions/`): shipped migrations are history; editing one
  adds risk to a module that must stay safe to re-run, and gains nothing.
* Query operators (`$in`, `$and`, `$exists`, ...): mostly nested expressions a constructor does not fit.
  The existing operator constructors are used where they fit; only stages are enforced.
* An update document passed straight to an update call (`update_one(filter, {'$set': ...})`) - not a
  pipeline position, so not a stage.

Pure tests: AST only, nothing is imported from the scanned modules
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCANNED_GLOB: str = 'cmdb/**/*.py'
BUILDER_MODULE: str = 'cmdb/manager/query_builder/builder.py'
UPDATER_PACKAGE: str = 'cmdb/database/updater/versions/'

# The stage names Builder has a constructor for, and the constructor to use instead
STAGE_CONSTRUCTORS: dict[str, str] = {
    '$match': 'match_',
    '$project': 'project_',
    '$unwind': 'unwind_',
    '$group': 'group_',
    '$sort': 'sort_',
    '$lookup': 'lookup_ / correlated_lookup_',
    '$graphLookup': 'graph_lookup_',
    '$limit': 'limit_',
    '$skip': 'skip_',
    '$count': 'count_',
    '$facet': 'facet_',
    '$unset': 'unset_',
    '$addFields': 'add_fields_',
    '$set': 'set_',
    '$replaceRoot': 'replace_root_',
}
PIPELINE_METHODS: frozenset[str] = frozenset({'append', 'add_pipe', 'insert'})


def _scanned_files() -> list[str]:
    """Every live cmdb module, repo-relative - builder.py and the updaters left out."""
    return sorted(
        relative for relative in (path.relative_to(REPO_ROOT).as_posix() for path in REPO_ROOT.glob(SCANNED_GLOB))
        if relative != BUILDER_MODULE and not relative.startswith(UPDATER_PACKAGE)
    )


def _in_pipeline_position(node: ast.Dict, parent: ast.AST | None) -> bool:
    """Whether a dict stands where a pipeline stage stands."""
    if isinstance(parent, (ast.List, ast.Return)):
        return True

    return (isinstance(parent, ast.Call) and node in parent.args
            and isinstance(parent.func, ast.Attribute) and parent.func.attr in PIPELINE_METHODS)


def find_raw_stages(relative_path: str) -> list[str]:
    """
    Lists the hand-written stages of one module

    Args:
        relative_path (str): The module, relative to the repository root

    Returns:
        list[str]: One `path:line: '$stage' -> Builder.constructor_` line per hand-written stage
    """
    tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding='utf-8'))
    parents: dict[int, ast.AST] = {
        id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    offences: list[str] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Dict) and len(node.keys) == 1 and isinstance(node.keys[0], ast.Constant)):
            continue

        stage = node.keys[0].value

        if stage in STAGE_CONSTRUCTORS and _in_pipeline_position(node, parents.get(id(node))):
            offences.append(f"{relative_path}:{node.lineno}: '{stage}' -> Builder.{STAGE_CONSTRUCTORS[stage]}")

    return offences


def test_the_scan_sees_the_code() -> None:
    """An empty glob would make the tripwire pass vacuously."""
    scanned = _scanned_files()

    assert len(scanned) > 500
    assert BUILDER_MODULE not in scanned
    assert not any(path.startswith(UPDATER_PACKAGE) for path in scanned)


def test_no_stage_is_written_by_hand() -> None:
    """The message names every hand-written stage and the constructor to use instead."""
    offences = [line for path in _scanned_files() for line in find_raw_stages(path)]

    assert not offences, 'Build these stages with their Builder constructor:\n' + '\n'.join(offences)


class TestTheDetector:
    """The scan itself, on hand-written snippets."""

    @pytest.mark.parametrize('source', [
        "pipeline = [{'$match': {'a': 1}}]",
        "pipeline.append({'$sort': {'a': 1}})",
        "builder.add_pipe({'$unwind': '$a'})",
        "pipeline.insert(0, {'$limit': 1})",
        "def stage():\n    return {'$project': {'a': 1}}",
        "stage = {'$lookup': {'from': 'x', 'pipeline': [{'$limit': 1}]}}",
        "collection.update_many({}, [{'$set': {'a': 1}}])",
    ], ids=['pipeline-list', 'append', 'add_pipe', 'insert', 'return', 'sub-pipeline', 'pipeline-update'])
    def test_a_pipeline_position_is_flagged(self, source: str, tmp_path: Path, monkeypatch) -> None:
        """Each position the scan claims to cover."""
        assert self._scan(source, tmp_path, monkeypatch)

    @pytest.mark.parametrize('source', [
        "collection.update_one({'a': 1}, {'$set': {'b': 2}})",
        "match = {'$in': [1, 2]}",
        "pipeline = [Builder.match_({'a': 1})]",
        "pipeline = [{'$match': {'a': 1}, '$sort': {'a': 1}}]",
        "pipeline = [{'$sample': {'size': 3}}]",
    ], ids=['update-document', 'operator', 'constructor', 'two-key-dict', 'stage-without-constructor'])
    def test_what_is_not_flagged(self, source: str, tmp_path: Path, monkeypatch) -> None:
        """An update document, an operator, a constructor call and non-stage dicts are all left alone."""
        assert not self._scan(source, tmp_path, monkeypatch)

    @staticmethod
    def _scan(source: str, tmp_path: Path, monkeypatch) -> list[str]:
        """Runs the detector over one snippet."""
        (tmp_path / 'snippet.py').write_text(source, encoding='utf-8')
        monkeypatch.setattr(f'{__name__}.REPO_ROOT', tmp_path)

        return find_raw_stages('snippet.py')

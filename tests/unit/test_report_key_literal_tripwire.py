"""
Tripwire: report code spells the document keys of CmdbReport and CmdbReportCategory through their enums, never as
string literals

Every key of a stored CmdbReport is a member of ``ReportKey``, every key of a CmdbReportCategory one of
``ReportCategoryKey`` (both in ``cmdb/models/reports_model/report_constants.py``). The models, their schemas and the
managers used to spell them as bare strings, because the enums lived in the route layer and could not be imported below
it. Each scan in ``SCANS`` fails on a string literal in a KEY position - a dict key, a subscript, the first argument of
``.get`` / ``.pop`` / ``.setdefault`` - whose value is one of its enum's values, in the code that handles that
document. A scanned entry is a module, or ``module::function`` for the one function of a module that handles it.

What it deliberately does not flag:

* a scan's ``generic`` keys: every model has ``public_id`` and ``name``, and report code reads them off types, objects
  and report categories as often as off reports - so the report scan leaves both alone. The category scan leaves only
  ``public_id``: ``name`` is the category's own key, and the category code reads it off nothing else.
* Index declarations (a dict carrying a ``keys`` entry): ``name`` / ``keys`` / ``unique`` are the DAO convention.

A model's ``REQUIRED_INIT_KEYS`` list counts as a key position too: its entries are document keys.

Pure tests: AST only, nothing is imported from the scanned modules
"""
import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from cmdb.models.reports_model.report_constants import ReportCategoryKey, ReportKey
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# Separates a module from the one function of it a scan covers
FUNCTION_SEPARATOR: str = '::'
INDEX_DECLARATION_KEY: str = 'keys'
KEY_ACCESS_METHODS: frozenset[str] = frozenset({'get', 'pop', 'setdefault'})

# A model attribute whose list entries are document keys
KEY_LIST_ATTRIBUTES: frozenset[str] = frozenset({'REQUIRED_INIT_KEYS'})


@dataclass(frozen=True)
class KeyScan:
    """
    One document's keys and the code that has to spell them through its enum

    Attributes:
        keys (type[Enum]): The document's key enum
        targets (tuple[str, ...]): Repo-relative modules, or ``module::function``
        generic (frozenset[str]): The enum values left alone, since the scanned code reads them off other documents
    """
    keys: type[Enum]
    targets: tuple[str, ...]
    generic: frozenset[str]

    def key_values(self) -> dict[str, str]:
        """
        Maps each flagged key value to the member to spell it with

        Returns:
            dict[str, str]: value -> ``Enum.MEMBER``, the generic values left out
        """
        return {member.value: f'{self.keys.__name__}.{member.name}' for member in self.keys
                if member.value not in self.generic}


SCANS: tuple[KeyScan, ...] = (
    KeyScan(ReportKey, (
        'cmdb/models/reports_model/cmdb_report.py',
        'cmdb/models/reports_model/report_query.py',
        'cmdb/class_schema/reports_model/cmdb_report_schema.py',
        'cmdb/manager/reports_manager.py',
        'cmdb/manager/report_categories_manager.py',
        'cmdb/manager/section_templates_manager.py',
        'cmdb/interface/rest_api/routes/report_routes/report_category_helper.py',
        'cmdb/interface/rest_api/routes/report_routes/report_routes.py',
        'cmdb/interface/rest_api/routes/report_routes/report_helper.py',
    ), frozenset({ReportKey.PUBLIC_ID.value, ReportKey.NAME.value})),
    KeyScan(ReportCategoryKey, (
        'cmdb/models/reports_model/cmdb_report_category.py',
        'cmdb/class_schema/reports_model/cmdb_report_category_schema.py',
        'cmdb/manager/report_categories_manager.py',
        'cmdb/interface/rest_api/routes/report_routes/report_category_helper.py',
        'cmdb/interface/rest_api/routes/report_routes/report_category_routes.py',
        'cmdb/framework/configuration_transfer/reset_scope.py',
        'cmdb/database/database_services/collection_validator.py::create_general_report_category',
    ), frozenset({ReportCategoryKey.PUBLIC_ID.value})),
)


def _scan_ids() -> list[str]:
    """One test id per scan: its enum"""
    return [scan.keys.__name__ for scan in SCANS]


def _scope(relative_target: str) -> ast.AST:
    """
    Parses a scanned target: the whole module, or the one function it names

    Args:
        relative_target (str): ``module`` or ``module::function``, repo-relative

    Raises:
        LookupError: When the module defines no such function

    Returns:
        ast.AST: The tree to scan
    """
    path, _, function = relative_target.partition(FUNCTION_SEPARATOR)
    tree: ast.AST = ast.parse((REPO_ROOT / path).read_text(encoding='utf-8'))

    if not function:
        return tree

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            return node

    raise LookupError(f'{path} defines no function {function}')


def _assigns_key_list(node: ast.AST) -> bool:
    """
    Whether a node assigns a list or tuple to one of KEY_LIST_ATTRIBUTES

    Args:
        node (ast.AST): Any node

    Returns:
        bool: True for ``REQUIRED_INIT_KEYS = [...]`` and its annotated form
    """
    if isinstance(node, ast.Assign):
        targets: list[ast.expr] = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return False

    return (isinstance(node.value, (ast.List, ast.Tuple))
            and any(isinstance(target, ast.Name) and target.id in KEY_LIST_ATTRIBUTES for target in targets))


def _key_nodes(tree: ast.AST) -> list[ast.AST]:
    """The nodes sitting in a key position, index declarations left out"""
    index_declarations: set[int] = {
        id(node) for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == INDEX_DECLARATION_KEY for key in node.keys)
    }
    nodes: list[ast.AST] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and id(node) not in index_declarations:
            nodes.extend(key for key in node.keys if key is not None)
        elif isinstance(node, ast.Subscript):
            nodes.append(node.slice)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in KEY_ACCESS_METHODS and node.args):
            nodes.append(node.args[0])
        elif _assigns_key_list(node):
            nodes.extend(node.value.elts)

    return nodes


def find_literal_keys(relative_target: str, key_values: dict[str, str]) -> list[str]:
    """
    Lists the key literals in one scanned target

    Args:
        relative_target (str): The module, or ``module::function``, relative to the repository root
        key_values (dict[str, str]): flagged key value -> the member carrying it

    Returns:
        list[str]: One ``target:line: 'key' -> Enum.MEMBER`` line per literal
    """
    return [
        f"{relative_target}:{node.lineno}: '{node.value}' -> {key_values[node.value]}"
        for node in _key_nodes(_scope(relative_target))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in key_values
    ]


@pytest.mark.parametrize('scan', SCANS, ids=_scan_ids())
def test_the_scan_sees_its_code(scan: KeyScan) -> None:
    """A target that names no module or function would make the tripwire pass vacuously"""
    for target in scan.targets:
        assert (REPO_ROOT / target.partition(FUNCTION_SEPARATOR)[0]).is_file(), target
        _scope(target)


@pytest.mark.parametrize('scan', SCANS, ids=_scan_ids())
def test_no_key_is_spelled_as_a_literal(scan: KeyScan) -> None:
    """The message lists every literal with the member to use instead"""
    key_values: dict[str, str] = scan.key_values()
    offences = [line for target in scan.targets for line in find_literal_keys(target, key_values)]

    assert not offences, f'Spell these keys through {scan.keys.__name__}:\n' + '\n'.join(offences)


def test_the_category_scan_flags_the_categorys_name() -> None:
    """``name`` is generic for the report scan but the category's own key for the category scan"""
    report_scan, category_scan = SCANS

    assert ReportKey.NAME.value not in report_scan.key_values()
    assert category_scan.key_values()[ReportCategoryKey.NAME.value] == 'ReportCategoryKey.NAME'


class TestTheDetector:
    """The scan itself, on hand-written snippets"""

    @pytest.mark.parametrize('source', [
        "x = {'type_id': 1}",
        "x = doc['selected_fields']",
        "x = doc.get('report_query')",
        "x = doc.pop('mds_mode', None)",
        "REQUIRED_INIT_KEYS = ['type_id']",
        "REQUIRED_INIT_KEYS: list[str] = ['type_id']",
    ], ids=['dict-key', 'subscript', 'get', 'pop', 'init-keys', 'annotated-init-keys'])
    def test_a_key_position_is_flagged(self, source: str, tmp_path: Path, monkeypatch) -> None:
        """Each key position the scan claims to cover"""
        assert self._scan(source, tmp_path, monkeypatch)

    @pytest.mark.parametrize('source', [
        "x = {'public_id': 1, 'name': 'a'}",
        "INDEX_KEYS = [{'keys': [('type_id', 1)], 'name': 'type_id', 'unique': False}]",
        "x = 'type_id'",
        "x = {'not_a_report_key': 1}",
    ], ids=['generic-keys', 'index-declaration', 'plain-string', 'unknown-key'])
    def test_what_is_not_flagged(self, source: str, tmp_path: Path, monkeypatch) -> None:
        """A value outside a key position, a generic key and an index declaration are left alone"""
        assert not self._scan(source, tmp_path, monkeypatch)

    @staticmethod
    def _scan(source: str, tmp_path: Path, monkeypatch) -> list[str]:
        """Runs the detector over one snippet"""
        (tmp_path / 'snippet.py').write_text(source, encoding='utf-8')
        monkeypatch.setattr(f'{__name__}.REPO_ROOT', tmp_path)

        return find_literal_keys('snippet.py', SCANS[0].key_values())

    def test_a_function_scope_sees_only_that_function(self, tmp_path: Path, monkeypatch) -> None:
        """``module::function`` leaves the rest of the module alone"""
        (tmp_path / 'snippet.py').write_text(
            "def seeding():\n    return {'predefined': True}\n\ndef other():\n    return {'predefined': True}\n",
            encoding='utf-8',
        )
        monkeypatch.setattr(f'{__name__}.REPO_ROOT', tmp_path)

        assert find_literal_keys('snippet.py::seeding', SCANS[1].key_values()) == [
            "snippet.py::seeding:2: 'predefined' -> ReportCategoryKey.PREDEFINED",
        ]

    def test_a_missing_function_is_an_error(self, tmp_path: Path, monkeypatch) -> None:
        """Never a vacuous pass"""
        (tmp_path / 'snippet.py').write_text("x = 1\n", encoding='utf-8')
        monkeypatch.setattr(f'{__name__}.REPO_ROOT', tmp_path)

        with pytest.raises(LookupError):
            find_literal_keys('snippet.py::absent', SCANS[1].key_values())

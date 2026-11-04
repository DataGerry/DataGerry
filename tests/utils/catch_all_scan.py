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
The AST helpers the catch-all tripwires share: which except arm catches every exception, and who owns it

A catch-all is any arm that catches a programming error: ``except Exception``, ``except BaseException``, a bare
``except:``, and either name inside a tuple (``except (KeyError, Exception)``). An arm's owner is the
``Class.function`` (or ``function``, or ``<module>``) it sits in
"""
import ast
# -------------------------------------------------------------------------------------------------------------------- #

# The handler types that catch everything a programming error raises - a bare ``except:`` counts too
CATCH_ALL_NAMES: frozenset[str] = frozenset({'Exception', 'BaseException'})
MODULE_LEVEL: str = '<module>'


def parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """
    Each node's parent in a parsed module

    Args:
        tree (ast.AST): The parsed module

    Returns:
        dict[ast.AST, ast.AST]: child -> parent
    """
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def owner_of(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """
    The ``Class.function`` (or ``function``, or ``<module>``) a node sits in

    Args:
        node (ast.AST): The node, normally an except handler
        parents (dict[ast.AST, ast.AST]): Each node's parent in its module

    Returns:
        str: The owner's qualified name
    """
    function: str | None = None
    current: ast.AST = node

    while current in parents:
        current = parents[current]

        if function is None and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = current.name
        elif function is not None and isinstance(current, ast.ClassDef):
            return f'{current.name}.{function}'

    return function or MODULE_LEVEL


def is_catch_all(handler: ast.ExceptHandler) -> bool:
    """
    Whether an except arm catches every exception - bare, ``Exception``/``BaseException``, or either inside a tuple

    Args:
        handler (ast.ExceptHandler): The except arm

    Returns:
        bool: True when the arm catches a programming error as well
    """
    if handler.type is None:
        return True

    names: list[ast.expr] = list(handler.type.elts) if isinstance(handler.type, ast.Tuple) else [handler.type]

    return any(isinstance(name, ast.Name) and name.id in CATCH_ALL_NAMES for name in names)

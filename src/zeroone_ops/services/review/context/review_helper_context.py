"""Bounded helper-following support for change-request review context."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import NamedTuple

from zeroone_ops.models.review import ReviewHelperContext
from zeroone_ops.services.shared.context_builder import _format_with_line_numbers

LOGGER = logging.getLogger(__name__)


class _ResolvedImportedHelper(NamedTuple):
    """Represent one resolvable imported helper symbol."""

    file_path: str
    symbol: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    lines: list[str]


def build_same_file_helper_context(
    *,
    repo_root: Path,
    file_path: str,
    raw_content: str,
    lines: list[str],
    changed_start: int,
    changed_end: int,
    enable_helper_following: bool,
    log_helper_following: bool,
    max_followed_helpers_per_function: int,
    max_followed_helper_lines: int,
    supported_paths: list[str],
    ignored_paths: list[str],
) -> tuple[list[ReviewHelperContext], int]:
    """Return bounded same-file helper context for one changed Python file."""
    if not enable_helper_following or max_followed_helpers_per_function <= 0:
        _log_helper_following(
            enabled=log_helper_following,
            message="Helper-following skipped for %s: disabled by config or zero budget.",
            args=(file_path,),
        )
        return [], 0
    if max_followed_helper_lines <= 0 or not file_path.endswith(".py"):
        _log_helper_following(
            enabled=log_helper_following,
            message="Helper-following skipped for %s: non-Python file or no helper line budget.",
            args=(file_path,),
        )
        return [], 0

    try:
        tree = ast.parse(raw_content)
    except SyntaxError:
        _log_helper_following(
            enabled=log_helper_following,
            message="Helper-following skipped for %s: parse_failed.",
            args=(file_path,),
        )
        return [], 0

    changed_function = _find_enclosing_python_function(
        tree=tree,
        changed_start=changed_start,
        changed_end=changed_end,
    )
    if changed_function is None:
        _log_helper_following(
            enabled=log_helper_following,
            message="Helper-following skipped for %s: no enclosing changed function.",
            args=(file_path,),
        )
        return [], 0

    available_helpers = _module_level_python_functions(tree)
    available_helpers.update(_same_file_python_methods(tree))
    imported_helpers = _project_local_imported_functions(
        repo_root=repo_root,
        file_path=file_path,
        tree=tree,
        supported_paths=supported_paths,
        ignored_paths=ignored_paths,
    )
    changed_class_name = _find_enclosing_python_class_name(
        tree=tree,
        changed_start=changed_start,
        changed_end=changed_end,
    )
    helper_calls = _collect_direct_same_file_calls(
        changed_function,
        enclosing_class_name=changed_class_name,
        same_file_class_names=set(_same_file_class_names(tree)),
    )

    helper_context: list[ReviewHelperContext] = []
    consumed_lines = 0
    seen_symbols: set[str] = set()
    for symbol in helper_calls:
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        if len(helper_context) >= max_followed_helpers_per_function:
            break

        helper_node = available_helpers.get(symbol)
        helper_file_path = file_path
        helper_lines = lines
        if helper_node is None:
            imported_helper = imported_helpers.get(symbol)
            if imported_helper is None:
                continue
            helper_file_path = imported_helper.file_path
            helper_node = imported_helper.node
            helper_lines = imported_helper.lines
            symbol = imported_helper.symbol
        elif helper_node is changed_function:
            continue

        if helper_file_path == file_path and helper_node is changed_function:
            continue

        start_line = helper_node.lineno
        end_line = helper_node.end_lineno or helper_node.lineno
        helper_line_count = end_line - start_line + 1
        if consumed_lines + helper_line_count > max_followed_helper_lines:
            continue

        helper_context.append(
            ReviewHelperContext(
                file_path=helper_file_path,
                symbol=symbol,
                start_line=start_line,
                end_line=end_line,
                content=_format_with_line_numbers(
                    start_line=start_line,
                    lines=helper_lines[start_line - 1 : end_line],
                ),
            )
        )
        consumed_lines += helper_line_count

    _log_helper_following(
        enabled=log_helper_following,
        message="Helper-following for %s included %s helper snippets using %s lines.",
        args=(file_path, len(helper_context), consumed_lines),
    )
    return helper_context, consumed_lines


def _find_enclosing_python_function(
    *,
    tree: ast.AST,
    changed_start: int,
    changed_end: int,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the smallest enclosing Python function for the changed lines."""
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= changed_start
        and (node.end_lineno or node.lineno) >= changed_end
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda node: (node.end_lineno or node.lineno) - node.lineno)


def _module_level_python_functions(
    tree: ast.AST,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return same-file module-level function definitions keyed by symbol."""
    if not isinstance(tree, ast.Module):
        return {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, node)
    return functions


def _same_file_python_methods(
    tree: ast.AST,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return same-file class methods keyed by ClassName.method."""
    if not isinstance(tree, ast.Module):
        return {}
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.setdefault(f"{node.name}.{child.name}", child)
    return methods


def _same_file_class_names(tree: ast.AST) -> list[str]:
    """Return module-level class names defined in the same file."""
    if not isinstance(tree, ast.Module):
        return []
    return [node.name for node in tree.body if isinstance(node, ast.ClassDef)]


def _find_enclosing_python_class_name(
    *,
    tree: ast.AST,
    changed_start: int,
    changed_end: int,
) -> str | None:
    """Return the smallest enclosing Python class name for the changed lines."""
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.lineno <= changed_start
        and (node.end_lineno or node.lineno) >= changed_end
    ]
    if not candidates:
        return None
    selected = min(candidates, key=lambda node: (node.end_lineno or node.lineno) - node.lineno)
    return selected.name


def _project_local_imported_functions(
    *,
    repo_root: Path,
    file_path: str,
    tree: ast.AST,
    supported_paths: list[str],
    ignored_paths: list[str],
) -> dict[str, _ResolvedImportedHelper]:
    """Return clear one-hop project-local imported functions keyed by local alias."""
    if not isinstance(tree, ast.Module):
        return {}

    imports: dict[str, _ResolvedImportedHelper] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None and node.level <= 0:
            continue
        target = _resolve_import_from_path(
            repo_root=repo_root,
            current_file=file_path,
            module=node.module,
            level=node.level,
        )
        if target is None:
            continue
        target_path, target_module_path = target
        if not _is_supported_helper_path(
            target_module_path,
            supported_paths=supported_paths,
            ignored_paths=ignored_paths,
        ):
            continue
        try:
            raw_content = target_path.read_text(encoding="utf-8")
            imported_tree = ast.parse(raw_content)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        available_functions = _module_level_python_functions(imported_tree)
        imported_lines = raw_content.splitlines()
        for alias in node.names:
            if alias.name == "*":
                continue
            function_node = available_functions.get(alias.name)
            if function_node is None:
                continue
            local_name = alias.asname or alias.name
            imports.setdefault(
                local_name,
                _ResolvedImportedHelper(
                    file_path=target_module_path,
                    symbol=alias.name,
                    node=function_node,
                    lines=imported_lines,
                ),
            )
    return imports


def _resolve_import_from_path(
    *,
    repo_root: Path,
    current_file: str,
    module: str | None,
    level: int,
) -> tuple[Path, str] | None:
    """Resolve one import-from target to a repo-local module file."""
    current_module_parts = Path(current_file).with_suffix("").parts
    if not current_module_parts:
        return None

    if level > 0:
        base_parts = list(current_module_parts[:-1])
        for _ in range(level - 1):
            if not base_parts:
                return None
            base_parts.pop()
        module_parts = [] if module is None else module.split(".")
        candidate_parts = base_parts + module_parts
    else:
        candidate_parts = [] if module is None else module.split(".")

    if not candidate_parts:
        return None

    candidate = repo_root.joinpath(*candidate_parts).with_suffix(".py")
    if candidate.exists() and candidate.is_file():
        return candidate, candidate.relative_to(repo_root).as_posix()

    package_init = repo_root.joinpath(*candidate_parts, "__init__.py")
    if package_init.exists() and package_init.is_file():
        return package_init, package_init.relative_to(repo_root).as_posix()

    return None


def _is_supported_helper_path(
    file_path: str,
    *,
    supported_paths: list[str],
    ignored_paths: list[str],
) -> bool:
    """Return whether one helper file path is in scope for helper-following."""
    if any(file_path.startswith(prefix) for prefix in ignored_paths):
        return False
    if not supported_paths:
        return True
    return any(file_path.startswith(prefix) for prefix in supported_paths)


def _collect_direct_same_file_calls(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    enclosing_class_name: str | None,
    same_file_class_names: set[str],
) -> list[str]:
    """Return direct same-file call names in first-seen order."""

    class _DirectCallCollector(ast.NodeVisitor):
        def __init__(
            self,
            root: ast.FunctionDef | ast.AsyncFunctionDef,
            *,
            enclosing_class_name: str | None,
            same_file_class_names: set[str],
        ) -> None:
            self._root = root
            self._enclosing_class_name = enclosing_class_name
            self._same_file_class_names = same_file_class_names
            self.calls: list[tuple[int, str]] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            if node is self._root:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            if node is self._root:
                self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if isinstance(node.func, ast.Name):
                self.calls.append((node.lineno, node.func.id))
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                qualifier = node.func.value.id
                method_name = node.func.attr
                if qualifier in {"self", "cls"} and self._enclosing_class_name is not None:
                    self.calls.append((node.lineno, f"{self._enclosing_class_name}.{method_name}"))
                elif qualifier in self._same_file_class_names:
                    self.calls.append((node.lineno, f"{qualifier}.{method_name}"))
            self.generic_visit(node)

    collector = _DirectCallCollector(
        function_node,
        enclosing_class_name=enclosing_class_name,
        same_file_class_names=same_file_class_names,
    )
    collector.visit(function_node)
    return [symbol for _, symbol in sorted(collector.calls, key=lambda item: item[0])]


def _log_helper_following(*, enabled: bool, message: str, args: tuple[object, ...]) -> None:
    """Emit one helper-following debug message when diagnostics are enabled."""
    if not enabled:
        return
    LOGGER.info(message, *args)

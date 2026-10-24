"""Dependency-free static check of the backend: every project import resolves to a real module and a real top-level
name, and no function or module uses an undefined name. Run from backend/:  python scripts/static_check.py
(It cannot replace the test-suite; it catches the typos a refactor introduces.)"""
import ast
import builtins
import symtable
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKGS = ("apps", "satyapan")
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def modules():
    for pkg in PKGS:
        for p in sorted((ROOT / pkg).rglob("*.py")):
            yield p


def modname(p: Path) -> str:
    parts = list(p.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def module_file(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return base.with_suffix(".py") if base.with_suffix(".py").exists() else None


_top_cache: dict[str, set[str]] = {}


def top_names(name: str) -> set[str]:
    if name not in _top_cache:
        f = module_file(name)
        tbl = symtable.symtable(f.read_text(), str(f), "exec")
        _top_cache[name] = {s.get_name() for s in tbl.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    return _top_cache[name]


def check_imports(p: Path, tree: ast.AST, errors: list[str]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in PKGS:
            if module_file(node.module) is None:
                errors.append(f"{p.relative_to(ROOT)}:{node.lineno} imports missing module {node.module}")
                continue
            for a in node.names:
                if a.name != "*" and a.name not in top_names(node.module) and module_file(f"{node.module}.{a.name}") is None:
                    errors.append(f"{p.relative_to(ROOT)}:{node.lineno} '{a.name}' is not defined in {node.module}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in PKGS and module_file(a.name) is None:
                    errors.append(f"{p.relative_to(ROOT)}:{node.lineno} imports missing module {a.name}")


def check_names(p: Path, errors: list[str]) -> None:
    src = p.read_text()
    if "import *" in src:
        return  # settings/__init__.py re-exports; nothing to resolve
    top = symtable.symtable(src, str(p), "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}

    def walk(tbl):
        for s in tbl.get_symbols():
            n = s.get_name()
            if not s.is_referenced() or n in BUILTINS:
                continue
            if tbl.get_type() == "module":
                undefined = n not in defined
            else:
                undefined = s.is_global() and n not in defined
            if undefined:
                errors.append(f"{p.relative_to(ROOT)}: undefined name '{n}' in {tbl.get_name()}()")
        for child in tbl.get_children():
            walk(child)
    walk(top)


def main() -> int:
    errors: list[str] = []
    for p in modules():
        tree = ast.parse(p.read_text(), str(p))
        check_imports(p, tree, errors)
        check_names(p, errors)
    for e in sorted(set(errors)):
        print("ERROR", e)
    print(f"checked {sum(1 for _ in modules())} modules: {len(set(errors))} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

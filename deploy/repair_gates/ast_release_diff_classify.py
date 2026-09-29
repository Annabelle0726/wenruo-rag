"""Classify every AST-level difference between the production baseline and the clean ninth file.

Requirement under audit: the release diff must be *quote-health only* - the single added guard inside
`async_chat.<locals>.decorate_answer`, with no other function body, module-level statement, import,
logging call or prompt string touched.

Nested definitions are replaced by placeholders in the *outer* function's comparison, so a change inside
a closure does not make its enclosing function look changed; each function is then judged on its own
direct body only. Any added/removed statement outside the authorised closure is a failure.
"""

import ast
import copy
import json
import pathlib
import sys


class Placeholder(ast.NodeTransformer):
    """Replace nested definitions with `pass` so an enclosing body is compared on its own statements."""

    def visit_FunctionDef(self, node):  # noqa: N802
        return ast.Pass()

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        return ast.Pass()

    def visit_ClassDef(self, node):  # noqa: N802
        return ast.Pass()


def load(path):
    source = pathlib.Path(path).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = []
            current = node
            while current is not None:
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(current.name)
                current = parents.get(current)
            functions[".".join(reversed(names))] = node
    return source, tree, functions


def own_body(node):
    """The function's own direct statements with nested definitions collapsed to a placeholder."""
    clone = copy.deepcopy(node)
    clone.body = [
        Placeholder().visit(statement)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        else statement
        for statement in clone.body
    ]
    return clone


def signature(node):
    return ast.dump(own_body(node), include_attributes=False)


prod_source, prod_tree, prod_functions = load(sys.argv[1])
clean_source, clean_tree, clean_functions = load(sys.argv[2])

only_prod = sorted(set(prod_functions) - set(clean_functions))
only_clean = sorted(set(clean_functions) - set(prod_functions))
changed = [
    name
    for name in sorted(set(prod_functions) & set(clean_functions))
    if signature(prod_functions[name]) != signature(clean_functions[name])
]

added, removed = {}, {}
for name in sorted(set(prod_functions) & set(clean_functions)):
    before = [ast.unparse(statement) for statement in own_body(prod_functions[name]).body]
    after = [ast.unparse(statement) for statement in own_body(clean_functions[name]).body]
    added_statements = [statement for statement in after if statement not in before]
    removed_statements = [statement for statement in before if statement not in after]
    if added_statements or removed_statements:
        added[name] = added_statements
        removed[name] = removed_statements

added = {name: statements for name, statements in added.items() if statements}
removed = {name: statements for name, statements in removed.items() if statements}


def top_level(tree):
    return [type(statement).__name__ for statement in tree.body]


def imports(tree):
    return sorted(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    )


report = {
    "functions_only_in_baseline": only_prod,
    "functions_only_in_clean": only_clean,
    "functions_with_changed_own_bodies": changed,
    "functions_with_added_statements": added,
    "functions_with_removed_statements": removed,
    "top_level_statements_equal": top_level(prod_tree) == top_level(clean_tree),
    "imports_equal": imports(prod_tree) == imports(clean_tree),
    "generic_fallback_in_clean": "generic_fallback" in clean_source,
    "prompt_literals_changed": any(
        isinstance(node, ast.Constant) and isinstance(node.value, str) and "通用技术规范" in node.value
        for node in ast.walk(clean_tree)
    ),
}

failures = []
if only_prod or only_clean:
    failures.append("function set changed")
if changed != ["async_chat.decorate_answer"]:
    failures.append(f"changed own-body functions = {changed}")
if list(added) != ["async_chat.decorate_answer"]:
    failures.append(f"functions with added statements = {list(added)}")
if removed:
    failures.append(f"functions with removed statements = {list(removed)}")
if not report["top_level_statements_equal"] or not report["imports_equal"]:
    failures.append("module-level structure or imports changed")
if report["generic_fallback_in_clean"]:
    failures.append("excluded branch present")
if report["prompt_literals_changed"]:
    failures.append("prompt wording changed")

report["DIALOG_SERVICE_RELEASE_DIFF"] = "QUOTE_HEALTH_ONLY" if not failures else "IMPURE"
report["failures"] = failures
print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
sys.exit(1 if failures else 0)

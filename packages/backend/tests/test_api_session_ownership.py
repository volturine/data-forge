import ast
from pathlib import Path


def test_api_route_handlers_do_not_receive_sync_sqlalchemy_sessions() -> None:
    modules_root = Path(__file__).parents[1] / 'modules'
    violations: list[str] = []

    for path in modules_root.rglob('routes.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_route = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == 'router'
                for decorator in node.decorator_list
            )
            if not is_route:
                continue

            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            for argument in arguments:
                annotation = argument.annotation
                has_session_annotation = annotation is not None and any(
                    isinstance(part, ast.Name)
                    and part.id == 'Session'
                    or isinstance(part, ast.Attribute)
                    and part.attr == 'Session'
                    or isinstance(part, ast.Constant)
                    and isinstance(part.value, str)
                    and part.value.endswith('Session')
                    for part in ast.walk(annotation)
                )
                if has_session_annotation:
                    violations.append(f'{path.relative_to(modules_root)}:{node.name}({argument.arg})')

    assert not violations, 'API route handlers must open and close synchronous DB sessions in their owning worker: ' + ', '.join(
        sorted(violations),
    )


def test_api_routes_do_not_bypass_owned_database_and_thread_admission() -> None:
    modules_root = Path(__file__).parents[1] / 'modules'
    violations: list[str] = []

    for path in modules_root.rglob('routes.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            called_name = function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else None
            if called_name in {'get_db', 'get_settings_db', 'run_in_threadpool'}:
                violations.append(f'{path.relative_to(modules_root)}:{node.lineno}:{called_name}')

    assert not violations, (
        'API routes must use run_api_blocking with run_db/run_settings_db instead of dependency-session generators or the generic thread pool: '
        + ', '.join(sorted(violations))
    )

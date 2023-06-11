from __future__ import annotations
from _ast import FunctionDef
import subprocess
import ast
import openai
import asyncio
import re
import click
from typing import Any


class FindOsEnvironAssignments(ast.NodeVisitor):
    def __init__(self):
        self.funcs = []
        self.bad_funcs = []

    def visit_FunctionDef(self, node: FunctionDef) -> Any:
        self.funcs.append(node)
        super().generic_visit(node)
        self.funcs.pop()

    def is_assignment_to_os_environt(self, node: ast.Assign):
        """
        Returns True if node looks like `os.environ["FOO"] = "bar"`
        """
        if len(node.targets) != 1:
            return False

        target = node.targets[0]

        if not isinstance(target, ast.Subscript):
            return False

        if not isinstance(target.value, ast.Attribute):
            return False

        if not isinstance(target.value.value, ast.Name):
            return False

        if target.value.value.id != "os":
            return False

        if target.value.attr != "environ":
            return False

        return True

    def visit_Assign(self, node: ast.Assign) -> Any:
        if self.is_assignment_to_os_environt(node):
            if (
                self.funcs
                and self.funcs[-1].name.startswith("test_")
                and self.funcs[-1] not in self.bad_funcs
            ):
                self.bad_funcs.append(self.funcs[-1])

        return super().generic_visit(node)


async def complete(prompt: str):
    resp = await openai.ChatCompletion.acreate(
        model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}]
    )
    return resp["choices"][0]["message"]["content"]


def extract_code_from_block(s: str) -> str:
    m = re.search(r"```python\n(.*)\n```", s, re.DOTALL)
    return m.group(1)


class Patch:
    def __init__(self, file: str, lineno: int, end_lineno: int, lines: list[str]):
        """
        lineno and end_lineno start from 0
        """
        self.file = file
        self.lineno = lineno
        self.end_lineno = end_lineno
        self.lines = lines


def apply_patches(lines: list[str], patches: list[Patch]) -> list[str]:
    offset = 0
    for patch in patches:
        lines = lines[: patch.lineno + offset] + patch.lines + lines[patch.end_lineno + offset :]
        offset += len(patch.lines) - (patch.end_lineno - patch.lineno)
    return lines


async def create_patch(file: str, lines: list[str], func: ast.FunctionDef):
    prompt_template = """
The following pytest function assigns a value to `os.environ`. This is not a good practice because
it can cause side effects in other tests. `monkeypatch.setenv` should be used instead.
Can you rewrite the function to use `monkeypatch.setenv`? Please make sure the new code is wrapped
with a python code block in markdown.

```python
{code}
```
"""
    click.echo(f"Creating patch for {file}:{func.lineno}")
    func_code = "\n".join(lines[func.lineno - 1 : func.end_lineno])
    resp = await complete(prompt_template.format(code=func_code))
    new_code = extract_code_from_block(resp)
    new_lines = new_code.split("\n")
    return Patch(
        file=file,
        lineno=func.lineno - 1,
        end_lineno=func.end_lineno,
        lines=new_lines,
    )


async def main():
    files = subprocess.check_output(["git", "ls-files", "tests/*.py"]).decode().splitlines()
    tasks = []
    for file in files:
        with open(file) as f:
            code = f.read()
            lines = code.split("\n")

        tree = ast.parse(code)
        visitor = FindOsEnvironAssignments()
        visitor.visit(tree)

        for func in visitor.bad_funcs:
            tasks.append(create_patch(file, lines, func))

    # Group patches by file
    patches = await asyncio.gather(*tasks)
    patches_by_file = {}
    for patch in patches:
        patches_by_file.setdefault(patch.file, []).append(patch)

    # Apply patches
    for file, patches in patches_by_file.items():
        with open(file) as f:
            lines = f.read().split("\n")

        lines = apply_patches(lines, patches)

        with open(file, "w") as f:
            f.write("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())

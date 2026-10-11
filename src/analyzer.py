import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    line: int
    kind: str
    message: str


@dataclass
class AnalysisResult:
    max_loop_depth: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def estimated_complexity(self) -> str:
        if self.max_loop_depth == 0:
            return "O(1)"
        if self.max_loop_depth == 1:
            return "O(n)"
        return f"O(n^{self.max_loop_depth})"


class LoopAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.depth = 0
        self.result = AnalysisResult()

    def _visit_loop(self, node):
        self.depth += 1
        self.result.max_loop_depth = max(self.result.max_loop_depth, self.depth)
        if self.depth >= 2:
            self.result.findings.append(Finding(
                node.lineno, "nested-loop",
                f"Loop nested {self.depth} levels deep. Can a dict/set lookup replace the inner loop?"))
        self.generic_visit(node)  # keep walking into the loop body
        self.depth -= 1

    visit_For = _visit_loop
    visit_While = _visit_loop

    def visit_Compare(self, node):
        if self.depth > 0 and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            self.result.findings.append(Finding(
                node.lineno, "membership-in-loop",
                "'in' check inside a loop. If the right side is a list, this is O(n) per check; use a set."))
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        is_str_value = isinstance(node.value, (ast.JoinedStr)) or (
            isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
        if self.depth > 0 and isinstance(node.op, ast.Add) and is_str_value:
            self.result.findings.append(Finding(
                node.lineno, "string-concat-in-loop",
                "String '+=' in a loop. Collect parts in a list and use ''.join(parts)."))
        self.generic_visit(node)


def analyze_source(source: str) -> AnalysisResult:
    tree = ast.parse(source)
    analyzer = LoopAnalyzer()
    analyzer.visit(tree)
    return analyzer.result


if __name__ == "__main__":
    path = Path(sys.argv[1])
    result = analyze_source(path.read_text(encoding="utf-8"))
    print(f"Estimated complexity: {result.estimated_complexity}")
    for f in result.findings:
        print(f"  line {f.line} [{f.kind}] {f.message}")
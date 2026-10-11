import copy
import importlib.util
import inspect
import io
import random
import timeit
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Failure:
    function: str
    input: Any
    expected: tuple[str, Any]  # ("ok", value) or ("error", ExceptionName)
    actual: tuple[str, Any]


@dataclass
class VerifyResult:
    passed: bool
    failures: list[Failure] = field(default_factory=list)


def load_module(path: Path):
    """Import a .py file by path. NOTE: this executes the file's code."""
    spec = importlib.util.spec_from_file_location(f"{path.stem}_loaded", path)
    module = importlib.util.module_from_spec(spec)
    with redirect_stdout(io.StringIO()):  # swallow top-level prints
        spec.loader.exec_module(module)
    return module


def make_inputs(n_cases: int = 200, seed: int = 0) -> list[list[int]]:
    rng = random.Random(seed)  # fixed seed -> reproducible tests
    cases = [[], [1], [1, 1], [1, 2, 3], [3, 3, 3]]
    for _ in range(n_cases):
        size = rng.randint(0, 12)
        cases.append([rng.randint(0, 5) for _ in range(size)])
    return cases


def call(fn, arg):
    try:
        with redirect_stdout(io.StringIO()):
            return ("ok", fn(copy.deepcopy(arg)))
    except Exception as e:
        return ("error", type(e).__name__)


def _testable_functions(module):
    """Functions defined in this file that take exactly one argument."""
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if fn.__module__ != module.__name__:
            continue
        if len(inspect.signature(fn).parameters) != 1:
            continue
        yield name, fn


def sample_behavior(path: Path, n: int = 8) -> list[str]:
    """Run the ORIGINAL on a few inputs and describe what it really does."""
    module = load_module(path)
    lines = []
    for name, fn in _testable_functions(module):
        for case in make_inputs(n_cases=3)[:n]:
            kind, value = call(fn, case)
            shown = repr(value) if kind == "ok" else f"raises {value}"
            lines.append(f"{name}({case!r}) -> {shown}")
    return lines


def verify(original_path: Path, optimized_path: Path) -> VerifyResult:
    try:
        orig = load_module(original_path)
        new = load_module(optimized_path)
    except Exception as e:
        print(f"  FAIL: optimized file could not be loaded ({type(e).__name__}: {e})")
        return VerifyResult(False, [Failure("<module>", None, ("ok", "loads"),
                                            ("error", f"{type(e).__name__}: {e}"))])

    failures: list[Failure] = []
    for name, fn in _testable_functions(orig):
        new_fn = getattr(new, name, None)
        if new_fn is None:
            print(f"  [{name}] FAIL: missing from optimized version")
            failures.append(Failure(name, None, ("ok", "function exists"),
                                    ("error", "function missing")))
            continue

        for case in make_inputs():
            expected, actual = call(fn, case), call(new_fn, case)
            if expected != actual:
                print(f"  [{name}] FAIL on input {case}")
                print(f"      original:  {expected[1]}")
                print(f"      optimized: {actual[1]}")
                failures.append(Failure(name, case, expected, actual))
                break
        else:
            big = [random.randint(0, 1000) for _ in range(2000)]
            with redirect_stdout(io.StringIO()):
                t_old = timeit.timeit(lambda: fn(list(big)), number=3)
                t_new = timeit.timeit(lambda: new_fn(list(big)), number=3)
            print(f"  [{name}] OK  original {t_old:.4f}s -> optimized {t_new:.4f}s "
                  f"({t_old / max(t_new, 1e-9):.1f}x faster)")
    return VerifyResult(passed=not failures, failures=failures)
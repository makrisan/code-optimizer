import sys
from pathlib import Path

from analyzer import analyze_source
from optimizer import (FORMAT_REMINDER, extract_code, feedback_message,
                       generate, start_chat)
from verifier import sample_behavior, verify

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
UNVERIFIED_DIR = OUTPUT_DIR / "unverified"
MAX_ATTEMPTS = 3


def process(path: Path) -> Path | None:
    """Returns the path of a VERIFIED rewrite, or None if none was found."""
    source = path.read_text(encoding="utf-8")
    if not source.strip():
        print(f"Skipping {path.name}: file is empty")
        return None
    try:
        result = analyze_source(source)
    except SyntaxError as e:
        print(f"Skipping {path.name}: invalid Python (line {e.lineno}: {e.msg})")
        return None

    print(f"\n{path.name}: estimated {result.estimated_complexity}")
    for f in result.findings:
        print(f"  line {f.line} [{f.kind}] {f.message}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    UNVERIFIED_DIR.mkdir(exist_ok=True)
    candidate_path = UNVERIFIED_DIR / path.name

    try:
        examples = sample_behavior(path)
    except Exception as e:
        print(f"  could not run the original to collect examples ({type(e).__name__}: {e})")
        examples = []
    messages = start_chat(source, result, examples)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n  attempt {attempt}/{MAX_ATTEMPTS}: optimizing...")
        reply = generate(messages, sample=attempt > 1)
        messages.append({"role": "assistant", "content": reply})

        code = extract_code(reply)
        if code is None:
            print("  no code block in reply, asking again")
            messages.append({"role": "user", "content": FORMAT_REMINDER})
            continue

        candidate_path.write_text(code, encoding="utf-8")
        print("  verifying...")
        outcome = verify(path, candidate_path)
        if outcome.passed:
            final = OUTPUT_DIR / path.name
            final.write_text(code, encoding="utf-8")
            candidate_path.unlink(missing_ok=True)
            print(f"  verified on attempt {attempt}, saved to output/{path.name}")
            return final

        messages.append({"role": "user", "content": feedback_message(outcome.failures[0])})

    print(f"\n  FAIL: no verified rewrite after {MAX_ATTEMPTS} attempts")
    print(f"  last attempt kept in output/unverified/{path.name}")
    return None


def main():
    files = [Path(a) for a in sys.argv[1:]] or sorted(INPUT_DIR.glob("*.py"))
    if not files:
        sys.exit("No .py files found in input/")
    for f in files:
        process(f)


if __name__ == "__main__":
    main()
import re
from functools import lru_cache
from typing import Any, cast

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from analyzer import AnalysisResult
from verifier import Failure

MODEL_NAME = "Qwen/Qwen2.5-Coder-3B-Instruct"  # try ...-3B-Instruct or 7B later


@lru_cache(maxsize=1)
def load_model() -> tuple[Any, Any]:
    """Load once, reuse for every file. Returns (tokenizer, model)."""
    # noinspection PyNoneFunctionAssignment
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    # noinspection PyNoneFunctionAssignment
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, dtype=torch.bfloat16, device_map="cpu"
    )
    return tokenizer, model


def build_prompt(source: str, result: AnalysisResult, examples: list[str]) -> str:
    if result.findings:
        issues = "\n".join(f"- line {f.line}: {f.message}" for f in result.findings)
    else:
        issues = "- none detected by static analysis"
    shown = "\n".join(examples) if examples else "(none)"
    return (
        "You are an expert Python performance engineer.\n"
        f"Estimated time complexity of the code below: {result.estimated_complexity}\n"
        f"Possible problems (hints only, may be wrong):\n{issues}\n\n"
        "These are the REAL outputs of the original code. Your rewrite must "
        f"match every one of them exactly:\n{shown}\n\n"
        "Rewrite the code to be faster. Rules:\n"
        "- Keep the same function names and parameters.\n"
        "- Match the real outputs above, even if the function's name suggests "
        "different behavior. Do not 'fix' bugs.\n"
        "- Do not add print statements or example calls.\n"
        "- Reply with ONE ```python code block only, then a one-line explanation.\n\n"
        f"```python\n{source}\n```"
    )


def start_chat(source: str, result: AnalysisResult, examples: list[str]) -> list[dict]:
    return [{"role": "user", "content": build_prompt(source, result, examples)}]


def _describe(outcome: tuple) -> str:
    kind, value = outcome
    return f"returns {value!r}" if kind == "ok" else f"raises {value}"


def feedback_message(failure: Failure) -> str:
    return (
        "Your rewrite is WRONG: it changes the behavior.\n"
        f"Function `{failure.function}` called with input {failure.input!r}:\n"
        f"- the ORIGINAL code {_describe(failure.expected)}\n"
        f"- YOUR version {_describe(failure.actual)}\n\n"
        "Do not guess what the function is supposed to do. Trace the ORIGINAL code "
        "step by step on that input and find what it really computes, then write a "
        "faster version that gives identical output for every input. "
        "Do not add print statements. "
        "Reply with ONE ```python code block only, then a one-line explanation."
    )


FORMAT_REMINDER = (
    "I could not find a ```python code block in your reply. "
    "Reply with exactly ONE ```python code block, then a one-line explanation."
)


def generate(messages: list[dict], sample: bool = False) -> str:
    """sample=False: greedy (deterministic). sample=True: random, for retries."""
    tokenizer, model = load_model()
    text = cast(str, tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    ))
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    if sample:
        output = model.generate(**inputs, max_new_tokens=400, do_sample=True,
                                temperature=0.8, top_p=0.95)
    else:
        output = model.generate(**inputs, max_new_tokens=400, do_sample=False)
    return cast(str, tokenizer.decode(
        output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True
    ))


def extract_code(reply: str) -> str | None:
    match = re.search(r"```(?:python)?\n(.*?)(?:```|\Z)", reply, re.DOTALL)
    return match.group(1).strip() if match else None
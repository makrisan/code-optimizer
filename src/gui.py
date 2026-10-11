import importlib.util
import subprocess
import sys

REQUIRED = {  # import name -> pip package name
    "customtkinter": "customtkinter",
    "torch": "torch",
    "transformers": "transformers",
    "accelerate": "accelerate",
}


def ensure_dependencies():
    missing = [pip for mod, pip in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    print("First run: installing", ", ".join(missing))
    print("(torch is large, this can take several minutes)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_dependencies()

import ctypes
import os
import queue
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

# Make sibling modules (analyzer, optimizer, main, verifier) importable
# no matter which folder the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

CONSOLE_MODE = "close"   # "close" = flash then disappear, "minimize" = stay in taskbar

BG = "#0f1117"
CARD = "#181b24"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#6a4be8"
TEXT_DIM = "#8b90a0"
GREEN, RED, YELLOW, BLUE = "#4ade80", "#f87171", "#fbbf24", "#60a5fa"


def handle_console():
    kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    if CONSOLE_MODE == "minimize":
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 6)  # 6 = SW_MINIMIZE
        return

    # "close": point print() at nowhere first, then detach the console after a moment
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

    def detach():
        time.sleep(1.5)
        kernel32.FreeConsole()  # the console window closes, the GUI process keeps running

    threading.Thread(target=detach, daemon=True).start()


class QueueWriter:
    """Looks like a file to print(), but sends text to the GUI thread."""

    def __init__(self, q: queue.Queue, drop_progress: bool = False):
        self.q = q
        self.drop_progress = drop_progress

    def write(self, text: str):
        if not text:
            return
        if self.drop_progress and ("\r" in text or "%|" in text):
            return  # skip download/loading progress-bar spam
        self.q.put(("log", text))

    def flush(self):
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Code Optimizer")
        self.geometry("880x620")
        self.minsize(720, 520)
        self.configure(fg_color=BG)
        self.q: queue.Queue = queue.Queue()

        # --- header ---
        ctk.CTkLabel(self, text="⚡ Code Optimizer",
                     font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", padx=24, pady=(20, 0))
        ctk.CTkLabel(self, text="Analyze complexity, rewrite with Qwen, verify the result",
                     text_color=TEXT_DIM).pack(anchor="w", padx=24, pady=(0, 12))

        # --- control card ---
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        card.pack(fill="x", padx=24)
        self.button = ctk.CTkButton(
            card, text="📂  Select file", width=150, height=40, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, state="disabled",
            command=self.select_file)
        self.button.grid(row=0, column=0, padx=16, pady=16)
        self.file_label = ctk.CTkLabel(card, text="No file selected", text_color=TEXT_DIM, anchor="w")
        self.file_label.grid(row=0, column=1, sticky="ew")
        self.status = ctk.CTkLabel(card, text="●  Starting...", text_color=YELLOW)
        self.status.grid(row=0, column=2, padx=16)
        card.grid_columnconfigure(1, weight=1)

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate", progress_color=ACCENT, height=6)
        self.progress.pack(fill="x", padx=24, pady=(10, 6))

        # --- log ---
        self.log = ctk.CTkTextbox(self, fg_color=CARD, corner_radius=14, wrap="word",
                                  font=("Consolas", 13), text_color="#d6d9e0")
        self.log.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        self.log.configure(state="disabled")
        for tag, color in [("ok", GREEN), ("bad", RED), ("warn", YELLOW),
                           ("info", BLUE), ("head", ACCENT)]:
            self.log.tag_config(tag, foreground=color)

        # --- footer ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(0, 16))
        self.out_label = ctk.CTkLabel(footer, text=f"Output folder: {OUTPUT_DIR}",
                                      text_color=TEXT_DIM, anchor="w")
        self.out_label.pack(side="left")
        ctk.CTkButton(footer, text="Open folder", width=110, fg_color="#262a36",
                      hover_color="#323848", command=self.open_output).pack(side="right")

        self.progress.start()
        threading.Thread(target=self.preload_model, daemon=True).start()
        self.poll_queue()

    # ---------- actions ----------
    def preload_model(self):
        """Load the model at startup so the first file isn't slow."""
        try:
            self.q.put(("status", ("●  Loading model...", YELLOW)))
            from optimizer import load_model
            with redirect_stderr(QueueWriter(self.q, drop_progress=True)):
                load_model()
            self.q.put(("ready", None))
        except Exception:
            self.q.put(("log", "ERROR loading model:\n" + traceback.format_exc()))
            self.q.put(("status", ("●  Model failed", RED)))

    def select_file(self):
        path = filedialog.askopenfilename(
            title="Choose a Python file", initialdir=ROOT / "input",
            filetypes=[("Python files", "*.py")])
        if not path:
            return
        self.file_label.configure(text=path, text_color="#d6d9e0")
        self.button.configure(state="disabled")
        self.progress.start()
        self.q.put(("status", ("●  Working...", YELLOW)))
        self.q.put(("log", f"=== {Path(path).name} ===\n"))
        threading.Thread(target=self.run, args=(Path(path),), daemon=True).start()

    def run(self, path: Path):
        """Runs in a background thread so the window stays responsive."""
        try:
            from main import process
            with redirect_stdout(QueueWriter(self.q)), \
                    redirect_stderr(QueueWriter(self.q, drop_progress=True)):
                saved = process(path)
            if saved:
                self.q.put(("log", f"\n✔ Verified rewrite saved to: {saved}\n\n"))
                self.q.put(("status", ("●  Done", GREEN)))
            else:
                self.q.put(("log", f"\nNo verified rewrite. Check {OUTPUT_DIR / 'unverified'}\n\n"))
                self.q.put(("status", ("●  Not verified", RED)))
        except Exception:
            self.q.put(("log", "\nERROR:\n" + traceback.format_exc() + "\n"))
            self.q.put(("status", ("●  Error", RED)))
        finally:
            self.q.put(("idle", None))

    def open_output(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        os.startfile(OUTPUT_DIR)  # Windows only

    # ---------- GUI-thread plumbing ----------
    def poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.append(payload)
                elif kind == "status":
                    self.status.configure(text=payload[0], text_color=payload[1])
                elif kind == "ready":
                    self.progress.stop()
                    self.status.configure(text="●  Ready", text_color=GREEN)
                    self.button.configure(state="normal")
                elif kind == "idle":
                    self.progress.stop()
                    self.button.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self.poll_queue)

    def append(self, text: str):
        tag = None
        if "FAIL" in text or "ERROR" in text or "Traceback" in text or "No verified" in text:
            tag = "bad"
        elif " OK " in text or text.startswith("\u2714"):
            tag = "ok"
        elif text.startswith("==="):
            tag = "head"
        elif "[nested-loop]" in text or "[membership" in text or "[string-concat" in text:
            tag = "warn"
        elif "optimizing" in text or "verifying" in text or "estimated" in text:
            tag = "info"
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")


if __name__ == "__main__":
    handle_console()
    try:
        App().mainloop()
    except Exception:
        err = traceback.format_exc()
        (ROOT / "gui_error.log").write_text(err, encoding="utf-8")
        from tkinter import messagebox
        messagebox.showerror("Code Optimizer crashed", err[-1500:])
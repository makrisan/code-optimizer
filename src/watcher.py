import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from analyzer import analyze_source
from optimizer import optimize, load_model

INPUT_DIR = Path(__file__).resolve().parent.parent / "input"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        self.process(Path(event.src_path))

    def process(self, path: Path):
        time.sleep(0.3)  # let the OS finish writing the file
        source = path.read_text(encoding="utf-8")
        if not source.strip():
            print(f"Skipping {path.name}: file is empty")
            return
        try:
            result = analyze_source(source)
        except SyntaxError as e:
            print(f"Skipping {path.name}: invalid Python (line {e.lineno}: {e.msg})")
            return
        print(f"\n{path.name}: estimated {result.estimated_complexity}")
        for f in result.findings:
            print(f"  line {f.line} [{f.kind}] {f.message}")

        print("  optimizing...")
        better = optimize(source, result)
        if better is None:
            print("  model returned no code block, nothing saved")
            return
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / path.name).write_text(better, encoding="utf-8")
        print(f"  saved to output/{path.name}")


def main():
    INPUT_DIR.mkdir(exist_ok=True)
    print("Loading model (first run downloads ~3 GB)...")
    load_model()
    observer = Observer()
    observer.schedule(NewFileHandler(), str(INPUT_DIR), recursive=False)
    observer.start()
    print(f"Watching {INPUT_DIR} ... (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
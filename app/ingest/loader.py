"""Read the pack files from disk. Any file problem is a 422 with the file name and line."""
import json
from pathlib import Path

from app.errors import AppError

PACK_FILES = {"prompts": "prompts.jsonl", "responses": "responses.jsonl", "citations": "citations.jsonl"}


def _bad_file(message: str, file: str, line: int | None = None) -> AppError:
    return AppError(422, "bad_file", message, {"file": file, "line": line})


def read_jsonl(path: Path) -> list:
    name = f"data/{path.name}"
    if not path.is_file():
        raise _bad_file(f"Missing file: {name}", name)
    rows = []
    try:
        # utf-8-sig also accepts files saved with a BOM (common from Windows editors).
        with path.open(encoding="utf-8-sig") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise _bad_file(f"Broken JSON in {name} line {line_no}: {e.msg}", name, line_no) from e
    except UnicodeDecodeError as e:
        raise _bad_file(f"{name} is not valid UTF-8", name) from e
    return rows


def read_run(path: Path) -> dict:
    name = f"data/{path.name}"
    if not path.is_file():
        raise _bad_file(f"Missing file: {name}", name)
    try:
        run = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _bad_file(f"Broken JSON in {name}", name) from e
    if not isinstance(run, dict):
        raise _bad_file(f"{name} must be a JSON object", name)
    return run


def load_pack(pack_dir: str) -> dict:
    data_dir = Path(pack_dir) / "data"
    records = {"run": read_run(data_dir / "run.json")}
    for kind, filename in PACK_FILES.items():
        records[kind] = read_jsonl(data_dir / filename)
    return records

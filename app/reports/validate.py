"""Evidence and completeness checks for report content. Code checks every reference; no LLM involved."""
import sqlite3

from app.analysis.preprocess import quote_in_text
from app.errors import AppError
from app.reports.models import ReportContent

TEXT_FIELDS = {
    "diagnostics": ("title", "pattern", "explanation", "test_evidence"),
    "remedies": ("title", "problem", "action", "expected_benefit", "uncertainty", "validation_step"),
}


def find_problems(conn: sqlite3.Connection, analysis_id: int, content: ReportContent, complete: bool) -> list[dict]:
    problems = []

    def add(path: str, code: str, message: str):
        problems.append({"path": path, "code": code, "message": message})

    answers = {r["response_id"]: r["answer_text"] for r in conn.execute(
        "SELECT r.response_id, r.answer_text FROM response_results rr "
        "JOIN responses r ON r.response_id = rr.response_id WHERE rr.analysis_id = ?", (analysis_id,))}

    def check_evidence(path: str, refs) -> None:
        for i, ref in enumerate(refs):
            if ref.response_id not in answers:
                add(f"{path}.evidence[{i}]", "unknown_response", f"{ref.response_id} is not in analysis {analysis_id}")
            elif not quote_in_text(ref.quote, answers[ref.response_id]):
                add(f"{path}.evidence[{i}].quote", "quote_not_found", f"Quote is not in the answer of {ref.response_id}")

    diagnostic_ids = [d.id for d in content.diagnostics]
    for kind, items in (("diagnostics", content.diagnostics), ("remedies", content.remedies)):
        ids = [x.id for x in items]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            add(kind, "duplicate_id", f"Id {dup} is used more than once")
        for i, item in enumerate(items):
            check_evidence(f"{kind}[{i}]", item.evidence)

    for i, r in enumerate(content.remedies):
        for d in r.diagnostic_ids:
            if d not in diagnostic_ids:
                add(f"remedies[{i}].diagnostic_ids", "unknown_diagnostic", f"Diagnostic {d} does not exist")
    priorities = [r.priority for r in content.remedies]
    if len(priorities) != len(set(priorities)):
        add("remedies", "duplicate_priority", "Each remedy needs its own priority")

    if complete:
        for kind in ("diagnostics", "remedies"):
            items = getattr(content, kind)
            if len(items) != 3:
                add(kind, "wrong_count", f"Exactly 3 {kind} are needed to submit, found {len(items)}")
            for i, item in enumerate(items):
                for field in TEXT_FIELDS[kind]:
                    if not getattr(item, field).strip():
                        add(f"{kind}[{i}].{field}", "missing_field", f"{field} is empty")
                if not item.evidence:
                    add(f"{kind}[{i}].evidence", "missing_evidence", "At least one evidence quote is needed")
        for i, r in enumerate(content.remedies):
            if not r.diagnostic_ids:
                add(f"remedies[{i}].diagnostic_ids", "missing_field", "A remedy must follow from a diagnostic")
    return problems


def validate_content(conn: sqlite3.Connection, analysis_id: int, content: ReportContent, complete: bool) -> None:
    problems = find_problems(conn, analysis_id, content, complete)
    if problems:
        raise AppError(422, "invalid_report", f"{len(problems)} problem(s) in the report.", problems)

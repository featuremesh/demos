"""Export authored benchmark sources into physically separate subject/oracle roots."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from typing import TYPE_CHECKING, Any

from featuremesh.helpers.sltest import parse_slt_snippet

if TYPE_CHECKING:
    from pathlib import Path

_TASK_LINE = re.compile(r"^\*\*(T\d+)\.\s*(.+?)\.\*\*\s*$", re.MULTILINE)
_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_SQL_FENCE = re.compile(r"\*\*L3\.\*\*\s*```sql\s*(.*?)```", re.DOTALL)
_L1 = re.compile(r"\*\*L1\.\*\*\s*(.*?)(?=\n\n\*\*L2|\Z)", re.DOTALL)
_SLT_TITLE = re.compile(r"^#\s+([A-Za-z0-9_]+)\s*$", re.MULTILINE)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_manifest(source: Path) -> dict[str, Any]:
    manifest_path = source / "benchmark.yaml"
    if not manifest_path.exists():
        raise ValueError(f"Missing benchmark.yaml in {source}")
    return dict(json.loads(manifest_path.read_text(encoding="utf-8")))


def _safe_source(source: Path, relative: str) -> Path:
    path = (source / relative).resolve()
    if not path.is_relative_to(source.resolve()):
        raise ValueError(f"Context path escapes suite root: {relative}")
    return path


def _sections(markdown: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(markdown))
    return {match.group(1): markdown[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(markdown)].strip() for index, match in enumerate(matches)}


def _questions(markdown: str) -> dict[str, str]:
    matches = list(_TASK_LINE.finditer(markdown))
    questions: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end() : end]
        next_heading = re.search(r"^##\s+", body, re.MULTILINE)
        if next_heading:
            body = body[: next_heading.start()]
        questions[match.group(1)] = f"{match.group(2)}.\n\n{body.strip()}"
    return questions


def _hint_sections(markdown: str) -> dict[str, str]:
    return {heading.split(".", maxsplit=1)[0]: content for heading, content in _sections(markdown).items() if re.fullmatch(r"T\d+\..*", heading)}


def _slt_blocks(content: str) -> dict[str, str]:
    matches = list(_SLT_TITLE.finditer(content))
    return {match.group(1): content[match.start() : matches[index + 1].start() if index + 1 < len(matches) else len(content)].strip() + "\n" for index, match in enumerate(matches)}


def _parse_expected_rows(result: str, schema: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in result.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        values = stripped.split("\t")
        row: dict[str, Any] = {}
        for index, value in enumerate(values):
            column = schema[index] if index < len(schema) else {"name": f"UNKNOWN_{index}", "type": "VARCHAR"}
            if column["type"] == "BIGINT":
                try:
                    row[column["name"]] = int(value)
                except ValueError:
                    row[column["name"]] = value
            else:
                row[column["name"]] = value
        rows.append(row)
    return rows


def _case_from_snippet(name: str, body: str, file_key: str, order: int) -> dict[str, Any]:
    snippet = parse_slt_snippet(name, file_key, order, body)
    schema = [
        {"name": column_name, "type": type_label}
        for (column_name, _fmt), type_label in zip(snippet.columns, snippet.schema, strict=False)
    ]
    if snippet.schema and len(schema) < len(snippet.schema):
        schema.extend(
            {"name": f"UNKNOWN_{index}", "type": type_label}
            for index, type_label in enumerate(snippet.schema[len(schema) :], start=len(schema))
        )
    return {
        "name": snippet.name,
        "query": snippet.featureql,
        "expected": {
            "tag": "Result",
            "schema": schema,
            "data": _parse_expected_rows(snippet.expected, schema),
        },
    }


def _case_index(content: str) -> dict[str, dict[str, Any]]:
    matches = list(_SLT_TITLE.finditer(content))
    cases = [
        _case_from_snippet(
            match.group(1),
            content[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(content)],
            "benchmark.slt",
            index + 1,
        )
        for index, match in enumerate(matches)
    ]
    index = {str(case["name"]): case for case in cases}
    if len(index) != len(cases):
        raise ValueError("Duplicate SLT snippet names")
    return index


def _clean_expected(expected: dict[str, Any]) -> dict[str, Any]:
    schema = list(expected["schema"])
    first_column = schema[0]["name"]
    data = [row for row in expected["data"] if not str(row.get(first_column, "")).startswith("##")]
    return {**expected, "schema": schema, "data": data}


def _expected_slt(case: dict[str, Any]) -> str:
    expected = _clean_expected(case["expected"])
    schema = expected["schema"]
    rows = "\n".join("\t".join("NULL" if row.get(column["name"]) is None else str(row[column["name"]]) for column in schema) for row in expected["data"])
    return "# schema: " + "|".join(str(column["type"]) for column in schema) + "\n" + rows + "\n"


def _write(path: Path, content: str | bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = content.encode() if isinstance(content, str) else content
    path.write_bytes(raw)
    return _hash(raw)


def _manifest_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _hash(path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file() and path.name != "manifest.json"}


def _validate_dependencies(tasks: list[dict[str, Any]]) -> None:
    task_ids = {str(task["id"]) for task in tasks}
    dependencies = {str(task["id"]): [str(item) for item in task.get("depends_on", [])] for task in tasks}
    unknown = sorted({dependency for values in dependencies.values() for dependency in values if dependency not in task_ids})
    if unknown:
        raise ValueError(f"Unknown task dependencies: {unknown}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"Cyclic task dependency involving {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)


def export_suite(source: Path, output: Path) -> tuple[Path, Path]:
    manifest = _read_manifest(source)
    if int(manifest.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported benchmark schema_version")
    _validate_dependencies(list(manifest["tasks"]))
    subject = output / "subject" / manifest["suite"]
    oracle = output / "oracle" / manifest["suite"]
    for root in (subject, oracle):
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

    question_text = _safe_source(source, manifest["questions"]).read_text(encoding="utf-8")
    hint_text = _safe_source(source, manifest["hints"]).read_text(encoding="utf-8")
    questions = _questions(question_text)
    hints = _hint_sections(hint_text)

    dataset_path = _safe_source(source, manifest["dataset"]["file"])
    dataset_content = dataset_path.read_text(encoding="utf-8")
    dataset_cases = _case_index(dataset_content)
    dataset_snippet = manifest["dataset"]["snippet"]
    if dataset_snippet not in dataset_cases:
        raise ValueError(f"Missing dataset snippet {dataset_snippet}")
    _write(subject / "dataset.sql", str(dataset_cases[dataset_snippet]["query"]))

    profile_metadata: dict[str, Any] = {}
    for profile_name in ("scratch", "prebuilt"):
        profile = manifest["feature_profiles"][profile_name]
        profile_content = _safe_source(source, profile["file"]).read_text(encoding="utf-8")
        cases = _case_index(profile_content)
        snippets = list(profile["snippets"])
        missing = [snippet for snippet in snippets if snippet not in cases]
        if missing:
            raise ValueError(f"Missing {profile_name} profile snippets: {missing}")
        rendered = "\n\n-- BENCH_EVAL_STATEMENT --\n\n".join(str(cases[snippet]["query"]) for snippet in snippets)
        if profile_name == "prebuilt":
            forbidden_markers = [
                str(marker).casefold()
                for marker in (
                    *[task["solution"] for task in manifest["tasks"]],
                    *manifest.get("forbidden_prebuilt_markers", []),
                )
            ]
            leaked_markers = [marker for marker in forbidden_markers if marker and marker in rendered.casefold()]
            if leaked_markers:
                raise ValueError(f"Prebuilt profile contains answer-specific markers: {leaked_markers}")
        _write(
            subject / "feature_profiles" / f"{profile_name}.featureql",
            rendered + "\n",
        )
        profile_metadata[profile_name] = {
            "namespace": profile.get("namespace"),
            "snippets": snippets,
        }

    for context in manifest["context"]:
        source_path = _safe_source(source, context["file"])
        section = _sections(source_path.read_text(encoding="utf-8")).get(context["heading"])
        if section is None:
            raise ValueError(f"Missing context heading {context['heading']}")
        _write(
            subject / "context" / f"{context['heading'].lower()}.md",
            f"# {context['heading']}\n\n{section}\n",
        )

    solution_path = _safe_source(source, manifest.get("solutions", {}).get("file", manifest["dataset"]["file"]))
    solution_content = solution_path.read_text(encoding="utf-8")
    solution_cases = _case_index(solution_content)
    solution_blocks = _slt_blocks(solution_content)
    sql_cases: dict[str, dict[str, Any]] = {}
    if manifest.get("sql_solutions"):
        sql_content = _safe_source(source, manifest["sql_solutions"]["file"]).read_text(encoding="utf-8")
        sql_cases = _case_index(sql_content)
    task_ids: set[str] = set()
    subject_tasks: list[dict[str, Any]] = []
    oracle_tasks: list[dict[str, Any]] = []
    for task in manifest["tasks"]:
        task_id = str(task["id"])
        if task_id in task_ids:
            raise ValueError(f"Duplicate task id {task_id}")
        task_ids.add(task_id)
        solution_name = str(task["solution"])
        if task_id not in questions or task_id not in hints:
            raise ValueError(f"Missing question or hint for {task_id}")
        if solution_name not in solution_cases or solution_name not in solution_blocks:
            raise ValueError(f"Missing solution snippet {solution_name}")
        hint = _L1.search(hints[task_id])
        oracle_sql = _SQL_FENCE.search(hints[task_id])
        oracle_name = task.get("oracle")
        if not hint or (not oracle_sql and not oracle_name):
            raise ValueError(f"Missing A1 or direct SQL oracle for {task_id}")
        task_subject = subject / "tasks" / task_id
        task_oracle = oracle / "tasks" / task_id
        _write(task_subject / "question.md", questions[task_id] + "\n")
        _write(task_subject / "hint.md", hint.group(1).strip() + "\n")
        case = solution_cases[solution_name]
        _write(task_oracle / "reference.featureql", str(case["query"]) + "\n")
        transition_path = None
        if task.get("transition"):
            transition_snippets = list(task["transition"])
            missing_transitions = [snippet for snippet in transition_snippets if snippet not in solution_cases]
            if missing_transitions:
                raise ValueError(f"Missing transition snippets for {task_id}: {missing_transitions}")
            transition_path = f"tasks/{task_id}/transition.featureql"
            _write(
                task_oracle / "transition.featureql",
                "\n\n-- BENCH_EVAL_STATEMENT --\n\n".join(str(solution_cases[snippet]["query"]) for snippet in transition_snippets) + "\n",
            )
        expected = _clean_expected(case["expected"])
        if oracle_name:
            if oracle_name not in sql_cases:
                raise ValueError(f"Missing SQL oracle snippet {oracle_name}")
            sql_case = sql_cases[oracle_name]
            if _clean_expected(sql_case["expected"]) != expected:
                raise ValueError(f"FeatureQL and SQL oracle expectations disagree for {task_id}")
            rendered_oracle = str(sql_case["query"]).removeprefix("/* SQL */").strip()
        else:
            assert oracle_sql is not None
            rendered_oracle = oracle_sql.group(1).strip()
        _write(task_oracle / "expected.slt", _expected_slt(case))
        _write(
            task_oracle / "expected.json",
            json.dumps(expected, indent=2, sort_keys=True) + "\n",
        )
        _write(task_oracle / "oracle.sql", rendered_oracle + "\n")
        subject_tasks.append({
            "id": task_id,
            "difficulty": int(task["difficulty"]),
            "question": f"tasks/{task_id}/question.md",
            "hint": f"tasks/{task_id}/hint.md",
            "episode_only": bool(task.get("episode_only", False)),
            "depends_on": list(task.get("depends_on", [])),
        })
        oracle_tasks.append({
            "id": task_id,
            "solution_snippet": solution_name,
            "reference": f"tasks/{task_id}/reference.featureql",
            "expected": f"tasks/{task_id}/expected.json",
            "oracle_sql": f"tasks/{task_id}/oracle.sql",
            "transition": transition_path,
        })

    for episode in manifest.get("episodes", []):
        episode_tasks = [str(task_id) for task_id in episode["tasks"]]
        if not episode_tasks or len(set(episode_tasks)) != len(episode_tasks):
            raise ValueError(f"Episode {episode['id']} must contain unique ordered tasks")
        missing_episode_tasks = sorted(set(episode_tasks) - task_ids)
        if missing_episode_tasks:
            raise ValueError(f"Episode {episode['id']} references unknown tasks: {missing_episode_tasks}")

    subject_manifest = {
        "schema_version": 1,
        "suite": manifest["suite"],
        "version": manifest["version"],
        "backend": manifest["backend"],
        "tool_profile": manifest["tool_profile"],
        "dataset_health_sql": manifest["dataset"]["health_sql"],
        "feature_profiles": profile_metadata,
        "tasks": subject_tasks,
        "episodes": manifest.get("episodes", []),
    }
    oracle_manifest = {
        "schema_version": 1,
        "suite": manifest["suite"],
        "version": manifest["version"],
        "tasks": oracle_tasks,
    }
    subject_manifest["hashes"] = _manifest_hashes(subject)
    oracle_manifest["hashes"] = _manifest_hashes(oracle)
    _write(
        subject / "manifest.json",
        json.dumps(subject_manifest, indent=2, sort_keys=True) + "\n",
    )
    _write(
        oracle / "manifest.json",
        json.dumps(oracle_manifest, indent=2, sort_keys=True) + "\n",
    )
    preflight_subject(subject, oracle)
    return subject, oracle


def preflight_subject(subject: Path, oracle: Path | None = None) -> None:
    forbidden = {
        "reference.featureql",
        "expected.slt",
        "expected.json",
        "oracle.sql",
    }
    leaked = [path.relative_to(subject).as_posix() for path in subject.rglob("*") if path.is_file() and path.name in forbidden]
    if leaked:
        raise ValueError(f"Oracle files leaked into subject package: {leaked}")
    if oracle is not None:
        subject_text = "\n".join(path.read_text(encoding="utf-8") for path in subject.rglob("*") if path.is_file())
        leaked_content = []
        for path in oracle.rglob("*"):
            if not path.is_file() or path.name == "manifest.json":
                continue
            oracle_content = path.read_text(encoding="utf-8").strip()
            if oracle_content and oracle_content in subject_text:
                leaked_content.append(path.relative_to(oracle).as_posix())
        if leaked_content:
            raise ValueError(f"Reference query content leaked into subject package: {leaked_content}")


def assistance_payload(subject: Path, oracle: Path, task_id: str, level: str) -> str:
    parts = [(subject / "tasks" / task_id / "question.md").read_text()]
    if level in {"A1", "A2", "A3"}:
        parts.append((subject / "tasks" / task_id / "hint.md").read_text())
    if level in {"A2", "A3"}:
        parts.append("Typed expected result:\n" + (oracle / "tasks" / task_id / "expected.json").read_text())
    if level == "A3":
        parts.append("Equivalent DuckDB SQL:\n```sql\n" + (oracle / "tasks" / task_id / "oracle.sql").read_text() + "```")
    if level not in {"A0", "A1", "A2", "A3"}:
        raise ValueError(f"Unknown assistance level {level}")
    return "\n\n".join(part.strip() for part in parts)

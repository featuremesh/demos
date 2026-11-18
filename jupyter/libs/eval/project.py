"""Per-run FeatureMesh project and project-named DuckDB lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from featuremesh.access import AccessClient
from featuremesh.config import set_default


@dataclass(frozen=True)
class Project:
    name: str
    reference: str
    project_id: str
    token: str


class ProjectController:
    def __init__(
        self,
        *,
        access_client: AccessClient,
        org: str | None,
        db_root: Path,
        cleanup_queue: Path,
    ) -> None:
        self.org = org
        self.db_root = db_root
        self.cleanup_queue = cleanup_queue
        self._access = access_client

    @classmethod
    def from_environment(cls) -> ProjectController:
        identity_token = os.getenv("FEATUREMESH_IDENTITY_TOKEN", "").strip()
        if not identity_token:
            raise RuntimeError("FEATUREMESH_IDENTITY_TOKEN is required")
        registry_url = (
            os.getenv("FEATUREMESH_REGISTRY_URL", "").strip()
            or os.getenv("FEATUREMESH_ACCESS_URL", "").strip()
            or "http://host.docker.internal:18001"
        )
        host = registry_url.rstrip("/")
        if host.endswith("/v1/access"):
            host = host[: -len("/v1/access")]
        set_default("access.host", host)
        org = os.getenv("FEATUREMESH_EVAL_ORG", "").strip() or None
        logs_root = Path(__file__).resolve().parent.parent.parent / "logs"
        db_root = os.getenv("FEATUREMESH_EVAL_DB_ROOT", str(logs_root / "bench_eval_db"))
        return cls(
            access_client=AccessClient(identity_token),
            org=org,
            db_root=Path(db_root),
            cleanup_queue=logs_root / "bench_eval" / "cleanup_pending.jsonl",
        )

    async def close(self) -> None:
        return None

    async def create(self) -> Project:
        name = f"ev{uuid.uuid4().hex[:12]}"
        created = await asyncio.to_thread(self._access.create_project, name, self.org)
        reference = str(created["project_reference"])
        generated = await asyncio.to_thread(self._access.generate_access_token, reference)
        return Project(
            name=name,
            reference=reference,
            project_id=str(created["project_id"]),
            token=str(generated["token"]),
        )

    async def delete(self, project: Project) -> None:
        first = await asyncio.to_thread(self._access.delete_project, project.reference)
        await asyncio.to_thread(
            self._access.delete_project,
            project.reference,
            first["validation_code"],
        )

    def delete_database(self, project: Project) -> None:
        for suffix in ("", ".wal"):
            (self.db_root / f"{project.name}.duckdb{suffix}").unlink(missing_ok=True)

    def queue_cleanup(self, project: Project, error: Exception) -> None:
        self.cleanup_queue.parent.mkdir(parents=True, exist_ok=True)
        with self.cleanup_queue.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({
                    "project_reference": project.reference,
                    "project_name": project.name,
                    "error": str(error),
                })
                + "\n"
            )

    async def reconcile(self) -> list[dict[str, Any]]:
        if not self.cleanup_queue.exists():
            return []
        pending = [json.loads(line) for line in self.cleanup_queue.read_text(encoding="utf-8").splitlines() if line.strip()]
        remaining: list[dict[str, Any]] = []
        for item in pending:
            project = Project(
                name=item["project_name"],
                reference=item["project_reference"],
                project_id="",
                token="",  # nosec B106 -- cleanup uses the controller identity token
            )
            try:
                await self.delete(project)
                self.delete_database(project)
            except Exception as exc:
                remaining.append({**item, "error": str(exc)})
        temporary = self.cleanup_queue.with_suffix(".tmp")
        temporary.write_text(
            "".join(json.dumps(item) + "\n" for item in remaining),
            encoding="utf-8",
        )
        temporary.replace(self.cleanup_queue)
        return remaining

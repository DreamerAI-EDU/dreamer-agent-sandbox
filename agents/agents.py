"""
Dreamer AI Phase 2 — Real Agents
Domain and Technical agents backed by OpenRouter Codex CLI.
Falls back to stub generation when OPENROUTER_API_KEY is not set.
"""

import os
import json
import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional
from .state_bus import StateBus, Message
from .sandbox_manager import SandboxManager, SandboxConfig, ResourceLockedError
from .codex_cli import generate_code, is_available

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    name: str
    bus: StateBus
    sandbox: SandboxManager
    trace_id: str


class CurriculumAgent:
    """Domain Agent: designs lesson specifications."""

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    async def execute(self, task_id: str, params: Dict) -> Dict:
        await self._report_status(task_id, "running")

        # Simulate work: create lesson spec
        spec = {
            "topic": params.get("topic", "General"),
            "grade_level": params.get("grade_level", 1),
            "learning_objectives": [
                "Understand core concepts",
                "Apply in practice problems",
                "Demonstrate mastery",
            ],
            "estimated_duration_minutes": 45,
            "materials_needed": ["Whiteboard", "Worksheets"],
            "api_endpoints": [
                "GET /api/lessons",
                "GET /api/lessons/{id}",
                "POST /api/lessons",
            ],
            "db_tables": [
                {
                    "name": "lessons",
                    "columns": [
                        "id UUID PRIMARY KEY",
                        "title TEXT NOT NULL",
                        "grade_level INTEGER",
                        "content JSONB",
                        "created_at TIMESTAMP DEFAULT NOW()",
                    ],
                }
            ],
        }

        # Write to sandbox
        ws_path = self.ctx.sandbox.get_workspace_path(
            f"feature/curriculum-{task_id[:8]}"
        )
        spec_path = os.path.join(ws_path, params.get("output_file", "lesson_spec.json"))
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)

        await self.ctx.sandbox.commit_output(
            ws_name=f"feature/curriculum-{task_id[:8]}",
            files=[spec_path],
            status="success",
        )

        await self._report_status(task_id, "completed")
        return {"spec_file": spec_path, "spec": spec}

    async def _report_status(self, task_id: str, status: str):
        msg = Message.create(
            topic=f"task.{task_id}.status",
            payload={"taskId": task_id, "agent": "curriculum", "status": status},
            source="agent:curriculum",
            trace_id=self.ctx.trace_id,
        )
        await self.ctx.bus.publish(msg)


class BackendAgent:
    """Technical Agent: generates API route code."""

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    async def execute(self, task_id: str, params: Dict) -> Dict:
        await self._report_status(task_id, "running")

        # Read input spec if provided
        spec = {}
        spec_from = params.get("spec_from", "")
        if spec_from:
            # Find spec file from curriculum agent output
            curriculum_ws = f"feature/curriculum-{spec_from[:8]}"
            spec_path = os.path.join(
                self.ctx.sandbox.base_dir, curriculum_ws, "lesson_spec.json"
            )
            if os.path.exists(spec_path):
                with open(spec_path) as f:
                    spec = json.load(f)

        # Generate API code
        endpoints = spec.get("api_endpoints", ["GET /api/lessons"])
        routes_code = await self._generate_routes(endpoints)

        ws_path = self.ctx.sandbox.get_workspace_path(f"feature/be-{task_id[:8]}")
        api_file = os.path.join(ws_path, params.get("output_file", "lesson_api.py"))
        with open(api_file, "w") as f:
            f.write(routes_code)

        # Simulate some work time
        await asyncio.sleep(0.3)

        await self.ctx.sandbox.commit_output(
            ws_name=f"feature/be-{task_id[:8]}",
            files=[api_file],
            status="success",
        )

        await self._report_status(task_id, "completed")
        return {"api_file": api_file, "endpoints": endpoints}

    async def _generate_routes(self, endpoints: list) -> str:
        if is_available():
            return await self._llm_generate_routes(endpoints)
        return self._stub_generate_routes(endpoints)

    async def _llm_generate_routes(self, endpoints: list) -> str:
        system_prompt = (
            "You are a backend engineer building a Flask API for an education platform. "
            "Generate complete, production-ready Python code. "
            "Output ONLY the Python code. No explanation, no markdown fences."
        )
        user_prompt = (
            "Generate a Flask Blueprint for a lesson management API.\n\n"
            "Requirements:\n"
            "- Use Flask Blueprint named 'lesson_bp' with url_prefix='/api/lessons'\n"
            "- Each endpoint must return JSON via jsonify()\n"
            "- Include proper docstrings, type hints, and error handling\n"
            "- Use in-memory list as a simple data store (no real database)\n"
            "- Implement full CRUD behavior (GET returns data, POST creates, etc.)\n\n"
            f"Endpoints:\n{chr(10).join(endpoints)}\n"
        )
        try:
            code = await generate_code(
                user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
            )
            code = code.strip()
            if code.startswith("```"):
                code = code.split("```")[1]
                if code.startswith("python"):
                    code = code[6:]
                code = code.strip()
            logger.info("BackendAgent: generated %d chars via OpenRouter", len(code))
            return code
        except Exception as exc:
            logger.warning("BackendAgent: OpenRouter call failed (%s), falling back to stub", exc)
            return self._stub_generate_routes(endpoints)

    @staticmethod
    def _stub_generate_routes(endpoints: list) -> str:
        code = '''"""Lesson API — Auto-generated by BackendAgent"""

from flask import Blueprint, request, jsonify

lesson_bp = Blueprint("lessons", __name__, url_prefix="/api/lessons")

'''
        for ep in endpoints:
            method, path = ep.split(" ", 1)
            method_lower = method.lower()
            route_path = path.replace("/api/lessons", "").strip() or "/"
            code += f"""
@lesson_bp.route("{route_path}", methods=["{method}"])
def {method_lower}_lessons{'_by_id' if '{id}' in route_path else ''}():
    return jsonify({{"status": "ok", "method": "{method}"}})
"""
        return code

    async def _report_status(self, task_id: str, status: str):
        msg = Message.create(
            topic=f"task.{task_id}.status",
            payload={"taskId": task_id, "agent": "be", "status": status},
            source="agent:be",
            trace_id=self.ctx.trace_id,
        )
        await self.ctx.bus.publish(msg)


class DatabaseAgent:
    """Technical Agent: generates SQL migration code."""

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    async def execute(self, task_id: str, params: Dict) -> Dict:
        await self._report_status(task_id, "running")

        # Read input spec
        spec = {}
        spec_from = params.get("spec_from", "")
        if spec_from:
            curriculum_ws = f"feature/curriculum-{spec_from[:8]}"
            spec_path = os.path.join(
                self.ctx.sandbox.base_dir, curriculum_ws, "lesson_spec.json"
            )
            if os.path.exists(spec_path):
                with open(spec_path) as f:
                    spec = json.load(f)

        # Generate SQL migration
        tables = spec.get("db_tables", [])
        sql = await self._generate_migration(tables)

        ws_path = self.ctx.sandbox.get_workspace_path(f"feature/db-{task_id[:8]}")
        sql_file = os.path.join(
            ws_path, params.get("output_file", "lesson_schema.sql")
        )
        with open(sql_file, "w") as f:
            f.write(sql)

        # Simulate work
        await asyncio.sleep(0.3)

        await self.ctx.sandbox.commit_output(
            ws_name=f"feature/db-{task_id[:8]}",
            files=[sql_file],
            status="success",
        )

        await self._report_status(task_id, "completed")
        return {"sql_file": sql_file, "tables": [t["name"] for t in tables]}

    async def _generate_migration(self, tables: list) -> str:
        if is_available():
            return await self._llm_generate_migration(tables)
        return self._stub_generate_migration(tables)

    async def _llm_generate_migration(self, tables: list) -> str:
        system_prompt = (
            "You are a database engineer designing schemas for an education platform. "
            "Generate PostgreSQL-compatible SQL migration code. "
            "Output ONLY the SQL. No explanation, no markdown fences."
        )
        table_specs = json.dumps(tables, indent=2)
        user_prompt = (
            "Generate a PostgreSQL migration for the following table specifications.\n\n"
            "Requirements:\n"
            "- Use UUID primary keys with gen_random_uuid() default\n"
            "- Include appropriate indexes for foreign keys and query patterns\n"
            "- Use proper PostgreSQL types (JSONB for flexible data, TIMESTAMPTZ for timestamps)\n"
            "- Add created_at TIMESTAMPTZ DEFAULT NOW() and updated_at TIMESTAMPTZ DEFAULT NOW()\n"
            "- Wrap in a transaction (BEGIN/COMMIT)\n"
            "- Add a header comment with migration name and description\n\n"
            f"Table specifications:\n{table_specs}\n"
        )
        try:
            code = await generate_code(
                user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
            )
            code = code.strip()
            if code.startswith("```"):
                code = code.split("```")[1]
                if code.lower().startswith("sql"):
                    code = code[3:]
                code = code.strip()
            logger.info("DatabaseAgent: generated %d chars via OpenRouter", len(code))
            return code
        except Exception as exc:
            logger.warning("DatabaseAgent: OpenRouter call failed (%s), falling back to stub", exc)
            return self._stub_generate_migration(tables)

    @staticmethod
    def _stub_generate_migration(tables: list) -> str:
        sql = """-- Migration: Lesson Management Schema
-- Auto-generated by DatabaseAgent

"""
        for table in tables:
            name = table["name"]
            columns = table.get("columns", [])
            sql += f"CREATE TABLE {name} (\n"
            sql += "    " + ",\n    ".join(columns)
            sql += "\n);\n\n"
        return sql

    async def _report_status(self, task_id: str, status: str):
        msg = Message.create(
            topic=f"task.{task_id}.status",
            payload={"taskId": task_id, "agent": "db", "status": status},
            source="agent:db",
            trace_id=self.ctx.trace_id,
        )
        await self.ctx.bus.publish(msg)

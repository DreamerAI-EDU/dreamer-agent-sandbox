"""
Dreamer AI Phase 1 — Sandbox Manager
Isolated workspace lifecycle, resource locking, output protocol.
"""

import os
import json
import uuid
import shutil
import asyncio
import tempfile
import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from state_bus import StateBus, Message


@dataclass
class SandboxConfig:
    agent: str
    task_id: str
    domain: str  # "ui" | "be" | "db"
    trace_id: str
    parent_span_id: str
    ttl_seconds: int = 900
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxOutput:
    ws_name: str
    task_id: str
    agent: str
    files: List[str]
    commit_sha: str
    status: str  # "success" | "failed" | "timeout"
    error: Optional[str] = None


class SandboxManager:
    """Manages isolated workspaces for agent code generation."""

    def __init__(self, bus: StateBus, base_dir: Optional[str] = None):
        self.bus = bus
        self.base_dir = base_dir or tempfile.mkdtemp(prefix="dreamer-sandboxes-")
        self._active_sandboxes: Dict[str, SandboxConfig] = {}
        os.makedirs(self.base_dir, exist_ok=True)

    async def create_sandbox(self, config: SandboxConfig) -> str:
        """Create an isolated workspace. Returns workspace path."""
        ws_name = f"feature/{config.domain}-{config.task_id[:8]}"
        ws_path = os.path.join(self.base_dir, ws_name.replace("/", "_"))
        os.makedirs(ws_path, exist_ok=True)

        # Acquire resource lock
        lock_key = f"{config.domain}-ws"
        lease = await self.bus.acquire_lock(
            domain=config.domain,
            resource_key=lock_key,
            agent=config.agent,
            mode="rw",
            ttl=config.ttl_seconds,
            trace_id=config.trace_id,
        )

        if not lease:
            raise ResourceLockedError(
                f"Sandbox lock for {config.domain} is held by another agent"
            )

        config.inputs["lease_id"] = lease
        self._active_sandboxes[ws_name] = config

        # Publish sandbox creation
        msg = Message.create(
            topic=f"sandbox.{ws_name}.status",
            payload={
                "wsName": ws_name,
                "taskId": config.task_id,
                "agent": config.agent,
                "status": "active",
                "path": ws_path,
            },
            source=f"sandbox:{config.domain}",
            trace_id=config.trace_id,
            parent_span_id=config.parent_span_id,
        )
        await self.bus.publish(msg)

        return ws_path

    async def commit_output(
        self, ws_name: str, files: List[str], status: str = "success", error: str = None
    ) -> SandboxOutput:
        """Commit sandbox output to State Bus for merge staging."""
        config = self._active_sandboxes.get(ws_name)
        if not config:
            raise ValueError(f"Unknown sandbox: {ws_name}")

        commit_sha = f"sha-{uuid.uuid4().hex[:12]}"
        output = SandboxOutput(
            ws_name=ws_name,
            task_id=config.task_id,
            agent=config.agent,
            files=files,
            commit_sha=commit_sha,
            status=status,
            error=error,
        )

        # Release lock
        if config.inputs.get("lease_id"):
            await self.bus.release_lock(config.inputs["lease_id"])

        # Publish output
        msg = Message.create(
            topic=f"sandbox.{ws_name}.output",
            payload={
                "wsName": ws_name,
                "taskId": config.task_id,
                "agent": config.agent,
                "files": files,
                "commitSha": commit_sha,
                "status": status,
                "error": error,
            },
            source=f"sandbox:{config.domain}",
            trace_id=config.trace_id,
            parent_span_id=config.parent_span_id,
        )
        await self.bus.publish(msg)

        del self._active_sandboxes[ws_name]
        return output

    def get_workspace_path(self, ws_name: str) -> str:
        return os.path.join(self.base_dir, ws_name.replace("/", "_"))

    async def cleanup(self):
        """Remove all sandbox directories."""
        for ws_name in list(self._active_sandboxes.keys()):
            config = self._active_sandboxes[ws_name]
            if config.inputs.get("lease_id"):
                await self.bus.release_lock(config.inputs["lease_id"])
        shutil.rmtree(self.base_dir, ignore_errors=True)


class ResourceLockedError(Exception):
    pass

"""
Dreamer AI Phase 2.1 — Subagent Registry
Thread-safe, lazy-init registry for Hermes domain agents.

Design:
- Agents register with kb_ownership, capabilities, mode_allowlist
- mode_allowlist=None → non-student-facing agent (excluded from list_by_mode)
- Lazy init: agent instances created on first get(), not at register time
- Thread-safe: threading.RLock for concurrent registration
"""

import threading
from typing import Dict, List, Optional, Set, Type, Any


class SubagentRegistry:
    """Central registry for all Hermes sub-agents.

    Singleton pattern — injected into HermesScheduler at init.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: Dict[str, dict] = {}      # name → registration metadata
        self._instances: Dict[str, object] = {}   # name → lazy-instantiated agent

    # ── Registration ──────────────────────────────────

    def register(
        self,
        name: str,
        agent_class: Type,
        kb_ownership: List[str],
        capabilities: List[str],
        mode_allowlist: Optional[List[str]] = None,
    ) -> None:
        """Register an agent class with metadata.

        Args:
            name: Unique agent name (e.g. "curriculum", "assessment")
            agent_class: Agent stub class (instantiated lazily on first get)
            kb_ownership: Knowledge bases this agent owns/controls
            capabilities: Capability tags this agent provides
            mode_allowlist: Student-facing modes this agent serves.
                None → non-student-facing (excluded from list_by_mode).
                List[str] → only these modes (DIRECT / CONTEXTUAL / HYBRID).

        Raises:
            ValueError: if name is already registered.
        """
        with self._lock:
            if name in self._entries:
                raise ValueError(f"Agent '{name}' is already registered")
            self._entries[name] = {
                "agent_class": agent_class,
                "kb_ownership": list(kb_ownership),
                "capabilities": list(capabilities),
                "mode_allowlist": (
                    list(mode_allowlist) if mode_allowlist is not None else None
                ),
            }

    # ── Lookup ─────────────────────────────────────────

    def get(self, name: str) -> Any:
        """Lookup an agent by name. Instantiates lazily on first access.

        Raises:
            KeyError: if name is not registered.
        """
        with self._lock:
            if name not in self._entries:
                raise KeyError(f"Agent '{name}' not found in registry")
            if name not in self._instances:
                self._instances[name] = self._entries[name]["agent_class"]()
            return self._instances[name]

    def list_all(self) -> List[str]:
        """Return all registered agent names."""
        with self._lock:
            return sorted(self._entries.keys())

    def list_by_kb(self, kb_name: str) -> List[str]:
        """Return agent names that own/control a specific knowledge base."""
        with self._lock:
            return sorted(
                name
                for name, entry in self._entries.items()
                if kb_name in entry["kb_ownership"]
            )

    def list_by_mode(self, mode: str) -> List[dict]:
        """Return agents that serve a given student-query mode.

        Only returns agents with non-None mode_allowlist (student-facing).
        Non-student-facing agents (ParentReport, Marketing) are excluded.

        Args:
            mode: One of "DIRECT", "CONTEXTUAL", "HYBRID"

        Returns:
            List of dicts: {"name": str, "capabilities": [...], "kb_ownership": [...]}
        """
        with self._lock:
            result = []
            for name, entry in self._entries.items():
                allowlist = entry["mode_allowlist"]
                if allowlist is None:
                    continue  # non-student-facing, skip
                if mode in allowlist:
                    result.append({
                        "name": name,
                        "capabilities": list(entry["capabilities"]),
                        "kb_ownership": list(entry["kb_ownership"]),
                    })
            return result

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._entries

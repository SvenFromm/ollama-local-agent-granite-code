from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.memory import MemoryStore
from agent.prompts import ACTION_STATIC_PREFIX, build_action_prompt, build_transform_prompt
from agent.state import TaskState


class PerformanceDesignTests(unittest.TestCase):
    def test_memory_prompt_context_excludes_completed_tasks_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp))
            memory.remember_task("old", "agent/supervisor_summary.txt stale answer")
            memory.remember_file("agent/supervisor_summary.txt")
            memory.remember_fact("durable fact")
            context = memory.prompt_context(3)
            self.assertEqual(context, {"facts": ["durable fact"]})
            self.assertNotIn("supervisor_summary", str(context))

    def test_action_prompt_has_stable_prefix_across_objectives(self) -> None:
        tools = [{"name": "read_file", "arguments": [{"name": "path", "required": True}]}]
        first = build_action_prompt(TaskState("task one"), tools, {"read_file"}, {"facts": []}, "READ")
        second = build_action_prompt(TaskState("task two"), tools, {"read_file"}, {"facts": []}, "READ")
        prefix_one = first.split("DYNAMIC STATE:", 1)[0]
        prefix_two = second.split("DYNAMIC STATE:", 1)[0]
        self.assertEqual(prefix_one, prefix_two)
        self.assertTrue(prefix_one.startswith(ACTION_STATIC_PREFIX))

    def test_action_prompt_does_not_include_large_observation_content(self) -> None:
        state = TaskState("choose next action")
        state.record("read_file", {"path": "x"}, {"ok": True, "path": "x", "content": "X" * 10000}, 12000)
        prompt = build_action_prompt(state, [], {"read_file"}, {"facts": []}, "READ")
        self.assertNotIn("X" * 100, prompt)
        self.assertLess(len(prompt), 5000)

    def test_transform_prompt_has_no_tool_protocol(self) -> None:
        prompt = build_transform_prompt("summarize source", "print('hello')")
        self.assertIn("VERIFIED SOURCE CONTENT", prompt)
        self.assertNotIn('"action":"read_file"', prompt)
        self.assertNotIn("AVAILABLE TOOLS", prompt)

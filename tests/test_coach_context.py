"""Tests for agents.coach_context: ContextVar-based per-request context."""

from __future__ import annotations

import asyncio
import unittest

from agents import coach_context
from agents.coach_context import CoachContext


def _make_ctx(account_number: str) -> CoachContext:
    return CoachContext(session=object(), account=object(), account_number=account_number)


class TestCoachContext(unittest.TestCase):
    def test_current_raises_when_unset(self):
        # Run in a fresh task to avoid leaking state from sibling tests.
        async def run():
            with self.assertRaises(RuntimeError):
                coach_context.current()
        asyncio.run(run())

    def test_set_and_get_in_same_task(self):
        async def run():
            ctx = _make_ctx("A")
            coach_context.set_current(ctx)
            self.assertIs(coach_context.current(), ctx)
        asyncio.run(run())

    def test_concurrent_tasks_see_independent_contexts(self):
        # Regression: the previous implementation used a module-level global,
        # so two requests racing through set_current would clobber each other.
        async def task_for(account_number: str, gate: asyncio.Event) -> str:
            coach_context.set_current(_make_ctx(account_number))
            # Yield to scheduler so the other task definitely runs between
            # set_current and current() — exposes the race if any.
            await asyncio.sleep(0)
            await gate.wait()
            return coach_context.current().account_number

        async def run():
            gate = asyncio.Event()
            t1 = asyncio.create_task(task_for("ACCT-A", gate))
            t2 = asyncio.create_task(task_for("ACCT-B", gate))
            await asyncio.sleep(0.01)
            gate.set()
            a, b = await asyncio.gather(t1, t2)
            self.assertEqual(a, "ACCT-A")
            self.assertEqual(b, "ACCT-B")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

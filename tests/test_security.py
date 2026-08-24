from __future__ import annotations

import unittest

from agent.security import shell_policy


class SecurityTests(unittest.TestCase):
    def test_normal_shell_allowed(self) -> None:
        self.assertTrue(shell_policy("whoami", "execute script whoami").allowed)

    def test_unrequested_sudo_blocked(self) -> None:
        decision = shell_policy("sudo apt update", "get latest news")
        self.assertFalse(decision.allowed)

    def test_unrequested_package_manager_blocked(self) -> None:
        decision = shell_policy("apt-get install curl", "inspect README.md")
        self.assertFalse(decision.allowed)

    def test_sudo_does_not_authorize_unrequested_apt(self) -> None:
        decision = shell_policy("sudo apt update", "run sudo whoami")
        self.assertFalse(decision.allowed)
        self.assertIn("APT", decision.reason)

    def test_destructive_git_blocked(self) -> None:
        decision = shell_policy("git reset --hard HEAD", "fix the code")
        self.assertFalse(decision.allowed)

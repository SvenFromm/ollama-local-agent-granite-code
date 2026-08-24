from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


# pattern, description, words that must explicitly occur in the user's objective
_DANGEROUS_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (r"\bsudo\b", "privileged sudo execution", ("sudo",)),
    (r"\b(?:apt|apt-get)\b", "APT package manager execution", ("apt", "apt-get")),
    (r"\bdnf\b", "DNF package manager execution", ("dnf",)),
    (r"\byum\b", "YUM package manager execution", ("yum",)),
    (r"\bpacman\b", "Pacman package manager execution", ("pacman",)),
    (r"\bzypper\b", "Zypper package manager execution", ("zypper",)),
    (r"\bmkfs(?:\.|\s|$)", "filesystem formatting", ("mkfs", "format")),
    (r"\bdd\s+.*\bof=/dev/", "raw device write", ("dd",)),
    (r"\b(?:shutdown|reboot|poweroff|halt)\b", "system power operation", ("shutdown", "reboot", "poweroff", "halt")),
    (r"\brm\s+[^\n]*-r[^\n]*\s+/(?:\s|$)", "recursive root deletion", ("rm",)),
    (r"\brm\s+[^\n]*-f[^\n]*\s+/(?:\s|$)", "forced root deletion", ("rm",)),
    (r"\bgit\s+reset\s+--hard\b", "destructive Git reset", ("reset", "--hard")),
    (r"\bgit\s+clean\s+-[^\n]*f", "destructive Git clean", ("git clean",)),
)


def shell_policy(command: str, objective: str) -> PolicyDecision:
    command_lower = command.lower()
    objective_lower = objective.lower()
    for pattern, description, required_terms in _DANGEROUS_PATTERNS:
        if not re.search(pattern, command_lower, flags=re.I):
            continue
        if not any(term in objective_lower for term in required_terms):
            return PolicyDecision(False, f"{description} was not explicitly requested")
    return PolicyDecision(True)

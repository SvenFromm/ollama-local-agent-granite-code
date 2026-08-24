# Contributing

Contributions are welcome. Changes should preserve the project's core design: deterministic Python owns execution state and Granite handles only reasoning/transformation that benefits from an LLM.

Before submitting a change:

1. Keep tool behavior deterministic and return structured `{"ok": ...}` results.
2. Preserve workspace path confinement for filesystem operations.
3. Do not weaken shell or network policy without documenting the security consequence.
4. Add a regression test for every real model/controller failure being fixed.
5. Avoid moving model-specific protocol handling into concrete tools.
6. Keep model prompts compact; prefer controller state over long conversational history.
7. Run:

```bash
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
```

All tests must pass before a pull request is merged.

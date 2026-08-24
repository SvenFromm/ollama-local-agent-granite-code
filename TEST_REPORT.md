# Test Report

## Scope

Validation covers the Granite-only controller, deterministic routers, performance-oriented prompt design, security policies, tools, workflow state, model-action normalization, and controller-owned transformation/write workflows.

## Commands

```bash
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
```

## Result

- Python compilation: **PASS**
- Unit tests: **57 passed, 0 failed**
- Runtime dependencies: Python standard library only
- Repository CI target: **Python 3.14**

## Performance regressions covered

- persistent completed-task answers are excluded from model prompt memory;
- historical changed-file paths are excluded from model prompt memory;
- action prompts retain a stable prefix across objectives;
- large observation bodies are excluded from action-selection prompts;
- transformation prompts do not carry the tool-action protocol;
- literal file creation does not call the model;
- natural-language working-directory listing does not call the model;
- latest-news retrieval does not call the action model;
- compound source transformation calls Granite once for content generation, not for tool sequencing;
- append/add-to-file tasks cannot switch to an unrelated historical output path;
- non-progress loops terminate early.

## Functional and security regressions covered

- direct Granite tool actions;
- legacy `action=tool` compatibility;
- nested `arguments` repair;
- completion aliases;
- observation echo rejection;
- natural-language direct routing;
- source/output path extraction;
- explicit append/write-mode extraction;
- READ → WRITE workflow restriction;
- FETCH → WRITE workflow restriction;
- controller-owned pagination;
- exact output-path enforcement;
- controller-owned write verification;
- workspace traversal rejection;
- symlink escape rejection;
- shell non-zero and bounded output behavior;
- operation-specific sensitive shell policy;
- invalid URL scheme rejection;
- loopback/private-network blocking;
- tool argument sanitation.

## Real-hardware test-run diagnosis

The 2026-08-24 test run used `granite-code:3b` with a 16,384-token context. The principal latency was Ollama prompt evaluation, not Python module dispatch. Ten cache-miss prompt evaluations averaged approximately **21.7 s** with an average of approximately **1,649 prompt tokens**; cached prompt evaluations averaged approximately **27 ms**. Generated actions were generally only 21–42 tokens.

The v0.3 changes therefore focus on prompt size, prompt-prefix reuse, deterministic routing, and elimination of unnecessary model calls. See `PERFORMANCE.md` for details.

## Notes

Network tests validate URL policy without requiring external internet access. Ollama inference is represented by deterministic fake responses in supervisor unit tests; the automated suite therefore does not require a running Ollama server or GPU.

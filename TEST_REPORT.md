# Test Report

Updated: 2026-08-24

## Validation

- `python3 -m unittest discover -s tests -v`: **11 tests passed**
- `python3 -m compileall -q main.py agent tools tests`: **passed**

## Fixed behaviors

- Default Granite context increased to 16,384 tokens.
- Natural-language directory listing is routed directly in Python and completes without an LLM loop.
- Natural-language simple file reads are routed directly in Python.
- General current-news requests route directly to the network tool instead of guessed local files.
- Web-intent tasks no longer expose local file or shell tools unless the objective requires writing fetched results.
- Repeated `read_file` calls on paginated files automatically advance to `next_line`.
- Identical non-progressing actions are blocked after the first execution.
- Repeated model-action loops are detected before consuming additional tool calls.
- Simple list/read tasks are completed by controller evidence rather than waiting for Granite to emit `complete`.
- Context compaction preserves system/objective state instead of truncating the beginning of the prompt.
- Post-write controller verification remains enabled.

## 2026-08-24 shell-routing fix

Explicit requests such as `execute script whoami` and `run command pwd` are routed directly to `run_shell` without an LLM call. This prevents Granite from substituting an unrelated command such as `python3 agent/supervisor.py`.

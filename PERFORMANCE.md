# Performance Notes

## 2026-08-24 test-run diagnosis

The attached real-hardware run showed that Python module splitting was not the source of the slowdown. The dominant cost was Granite prompt evaluation on cache misses.

Observed characteristics from the run:

- model: `granite-code:3b`;
- Ollama context: 16,384 tokens;
- cache-miss prompts: approximately 1,445–1,857 tokens;
- 10 observed cache-miss prompt evaluations averaged approximately 21.7 seconds;
- median cache-miss prompt evaluation was approximately 21.4 seconds;
- average cache-miss prompt length was approximately 1,649 tokens;
- cached prompt evaluations were approximately 27 ms on average;
- generated controller actions were typically only 21–42 tokens.

The conclusion is that prompt prefill, not Python dispatch and not output generation, dominated latency.

## v0.3 performance changes

### Persistent-memory isolation

Completed task answers and historical changed-file paths are no longer sent to Granite on every iteration. Only explicitly stored durable facts are eligible for prompt memory.

This both reduces prompt size and prevents stale paths such as `agent/supervisor_summary.txt` from contaminating unrelated tasks.

### Stable action-prompt prefix

The Granite action prompt now begins with a stable instruction block and stable registered-tool schema. Task-specific state is appended only after a `DYNAMIC STATE` boundary.

This is designed to maximize llama.cpp/Ollama prefix-cache reuse across independent tasks.

### Smaller action-generation budget

Controller actions use `AGENT_ACTION_NUM_PREDICT=96` by default. Transformations use a separate `AGENT_TRANSFORM_NUM_PREDICT=384` budget.

### Dedicated transformation path

For tasks where Python already knows the workflow, Granite is not asked to select tools.

Examples:

- `create a file called test.txt with the content: Hello World!` → no model call;
- `list files of the working directory` → no model call;
- `get latest news` → deterministic network fetch plus Python RSS extraction;
- `append the file test.txt with a description about your model` → one short transformation call, then Python selects `append_file` and the exact target path;
- `read source.py and summarize it in summary.txt` → Python reads, Granite transforms, Python writes and verifies.

### Bounded non-progress loops

Ambiguous autonomous workflows terminate after a configurable number of consecutive non-progress iterations rather than spending all 24 iterations repeating a blocked action.

Default:

```bash
AGENT_MAX_NONPROGRESS_ITERATIONS=3
```

### Leaner Ollama logging

The enormous Ollama `context` token array is no longer written to debug logs. The agent logs useful timing metrics instead:

```text
OLLAMA METRICS prompt_tokens=... prompt_ms=... eval_tokens=... eval_ms=...
```

## Recommended runtime settings

```bash
export AGENT_NUM_CTX=16384
export AGENT_ACTION_NUM_PREDICT=96
export AGENT_TRANSFORM_NUM_PREDICT=384
export AGENT_TEMPERATURE=0
export AGENT_KEEP_ALIVE=30m
```

The 16K context should remain fully GPU-resident on the target system. Increasing context beyond the point where CPU offload begins is expected to hurt autonomous-agent latency more than the additional context helps.

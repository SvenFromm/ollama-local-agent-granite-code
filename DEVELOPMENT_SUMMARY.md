# Development Summary

## Purpose

This repository explores how a small, local code-completion model can be used as the reasoning component of an autonomous coding agent on older GPU hardware. The current target is `granite-code:3b` through Ollama with a 16,384-token context.

The central engineering conclusion is that reliable autonomy with a small completion-oriented model requires **more deterministic controller logic, not more prompt complexity**.

## Evolution

The project began as a single Python script and initially experimented with larger Qwen, Gemma, and Llama models. Those models could provide stronger reasoning but produced substantially higher inference latency and thermal load on the target GPU. Granite Code 3B provided much faster inference but exposed weaknesses in autonomous sequencing and ad-hoc JSON tool protocols.

Observed failure modes included:

- direct tool names instead of wrapper actions;
- nested `arguments` objects;
- copied tool observations;
- `return`/`done` instead of `complete`;
- repeated reads after successful source retrieval;
- premature completion before writing output files;
- hallucinated local files for internet tasks;
- unrelated shell actions;
- duplicate successful actions;
- excessive reliance on the LLM for deterministic operations.

The implementation evolved into a modular, Granite-specific controller that compensates for these predictable behaviors.

## Current responsibility split

### Python controller

Python owns:

- objective analysis;
- source/output path extraction;
- deterministic direct routing;
- workflow state;
- phase-specific tool exposure;
- action parsing and normalization;
- tool execution;
- workspace confinement;
- shell safety policy;
- network target validation;
- pagination;
- duplicate/loop prevention;
- output verification;
- completion enforcement;
- persistent memory;
- prompt compaction;
- CLI and logging.

### Granite Code

Granite is used for:

- reasoning that cannot be expressed deterministically;
- source-code understanding;
- summarization and transformation;
- code generation;
- selecting the next semantic action from a controller-restricted tool set.

## 2026 controller decomposition

The previous supervisor had grown beyond 2,000 lines. The current implementation separates its responsibilities into:

- `action_parser.py` — Granite JSON extraction and normalization;
- `objective.py` — task requirement and path detection;
- `direct_router.py` — deterministic non-LLM routing;
- `workflow.py` — READ/FETCH/WRITE completion policy;
- `security.py` — sensitive shell-operation policy;
- `state.py` — task observations and evidence;
- `tool_registry.py` — tool metadata, display, sanitation, and dispatch;
- `supervisor.py` — orchestration loop only.

The resulting `supervisor.py` is approximately one-sixth of the size of the previous monolithic version.

## Deterministic compound workflows

For a task such as:

```text
read agent/supervisor.py and summarize it in supervisor_summary.txt
```

Python derives the source and destination and executes:

```text
READ SOURCE (controller)
        ↓
TRANSFORM (Granite)
        ↓
WRITE OUTPUT (tool)
        ↓
VERIFY OUTPUT (controller)
        ↓
COMPLETE
```

Granite is not allowed to return to `read_file` once the source phase is complete. If it attempts to do so, the workflow rejects the action and exposes only the write tools.

## Network hardening

`curl_internet` now performs URL validation before a request and on redirects. By default it blocks targets resolving to private, loopback, link-local, multicast, reserved, or unspecified addresses. This reduces the risk of an autonomous model using the HTTP tool to access local services or metadata endpoints.

Private network access can be enabled explicitly with:

```bash
export AGENT_ALLOW_PRIVATE_NETWORK=1
```

## Shell hardening

The shell tool remains powerful by design, but the controller blocks sensitive operations unless the operation itself is explicitly present in the user's objective. Policy includes privileged execution, package managers, filesystem formatting, raw-device writes, power operations, destructive root deletion, and destructive Git cleanup/reset operations.

Policy checks are operation-specific: requesting `sudo whoami`, for example, does not automatically authorize an unrelated `apt` command.

## Context strategy

The default context is 16,384 tokens while Granite output is kept to 256 tokens by default. The additional context is used for relevant source evidence rather than verbose model reasoning. Tool outputs are bounded, recent observations are retained, and oversized prompts are compacted.

## Verification philosophy

The model is not trusted to declare that a side effect occurred. A file-writing task is complete only when a write tool succeeds and the controller independently reads the output back. Likewise, network and source-read requirements are tracked in `TaskState` as evidence rather than inferred from model prose.

## Testing

The performance-refined release passes 57 unit tests plus Python `compileall` validation. Tests cover:

- Granite action variants;
- nested argument normalization;
- observation-echo rejection;
- deterministic routing;
- objective/path analysis;
- read-to-write workflow transitions;
- web-to-write workflow transitions;
- completion rejection;
- workspace traversal and symlink escape;
- shell success/failure/output bounds;
- shell sensitive-operation policy;
- public/private URL validation;
- tool argument sanitation;
- controller source pagination;
- output-path enforcement;
- automatic post-write verification;
- direct shell/list execution without model calls.

## Guiding principle

> Use the LLM for transformations and decisions that require an LLM; use deterministic Python for everything that does not.


## Performance refinement — v0.3

A real-hardware test run after the module split showed that the Python refactor itself was not responsible for slower execution. Cache-miss Granite prompts of roughly 1,445–1,857 tokens spent about 18–25 seconds in prompt evaluation, while cached evaluations were approximately 27 ms.

The controller was therefore changed to reduce and stabilize model input rather than recombine modules. Persistent task answers and historical file paths are no longer included in every prompt, which also eliminates cross-task contamination observed when Granite repeatedly selected `agent/supervisor_summary.txt` for unrelated tasks.

The action prompt now has a stable prefix and compact dynamic state. The controller uses a separate transformation prompt for content-generation work. Known workflows now execute as deterministic pipelines: Python owns reads, target paths, tool selection, verification, and simple RSS extraction; Granite is called only where language/code transformation is required.

Literal file writes, common directory listings, explicit shell requests, and default latest-news retrieval can complete without an LLM action-selection call. Append/update tasks with a known target use one short transformation call and cannot silently switch to a stale historical path.

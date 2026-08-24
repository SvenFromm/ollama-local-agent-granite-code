# ollama-local-agent-granite-code
This repository is concerned with the creation to drive a locally running llm module with a self created python agent, using ollama and granite-code:3b on a vulkan GPU

## Background:
I have found an old AMD FirePro S7150 GPU (2016) cheaply with 8GB VRAM and was keen to experiment with locally running llm models.
CPU: AMD Ryzen 9 5950X / RAM: 64GB
The aim was to read files locally for further analysis, without the need to upload those.

## Process Overview:
- experimentation with a few unix versions, because the native driver support for the AMD FirePro has ended, hence experimenting with Ubuntu 20.04.2 and SUSE 15 SP2, but both releases have had compatibility issues to run the native driver, finally settled on Ubuntu 26.04 with mesa-radv driver. 
- to drive the llm a local agent is required, but e.g. CrewAI does not support latest Python V3.14.4, hence decided to develop the agent
- first version was a simple call in a Python program, this continuously evolved into a small project, which still has to be finalized

## Results:
- the FirePro is able to run a qwen3.5:9b model, with a context of up to 32k but it quickly runs into overheating issue (about 12 sec).
- generation speed for qwen3.5:9b with 32k context is about 16 token/s, with 16k context about 19 token/s but require external cooling, which is why the approach to get the largest possible model into the GPU has been abandoned
- code quality with local llm models has not been satisfactory, hence experimentation with thinking models like gemma4:4b, qwen3.5:8b, or llama3.1:8b was stopped, nevertheless the hardware was able to fit the models
- switching to non-thinking models, e.g. granite-code:8b or granite-code:3b has been expected to be beneficial. The issue with these models has been that the code quality is even worse, but at least they produced output at a reasonable speed.
- generation speed for granite-code:8b with 16k context has been 23 token/s, for granite-code:3b with 16k context the has been **49 token/s** 
- the first code was one large python file, to which logging and unit testing have been added for debugging purposes, but which has ultimately been rewritten in a modular manner
- in the end the agent was optimized for granite-code:3b with 16k context, exposing the following tools to the model:

## Target environment

The defaults are tuned for the development environment used for this project:

- Ubuntu / Linux
- Python 3.14+
- Ollama 0.32+
- `granite-code:3b`
- 16,384-token context
- local GPU inference

Default inference settings:

```text
model        granite-code:3b
context      16384
action_predict     96
transform_predict 384
temperature  0.0
top_p        0.85
top_k        20
```

All settings can be overridden through environment variables; see `agent/config.py`.

## Architecture

```text
User objective
      │
      ▼
Direct Router ───────────────► deterministic tool execution
      │
      ▼
Objective Analyzer
      │
      ▼
Workflow Policy
      │
      ▼
Granite Action Parser ◄────── Granite Code / Ollama
      │
      ▼
Security + Tool Policy
      │
      ▼
Tool Registry
      │
      ├── files
      ├── shell
      └── network
      │
      ▼
Task State + Verification
      │
      ├── incomplete ─────────► next Granite action
      └── complete ───────────► user result
```

The former 2,000+ line supervisor has been decomposed. `agent/supervisor.py` is now focused on orchestration, while parsing, routing, objective analysis, workflow policy, and security are separate modules.

## Repository structure

```text
.
├── main.py
├── agent/
│   ├── action_parser.py
│   ├── config.py
│   ├── direct_router.py
│   ├── logging_setup.py
│   ├── memory.py
│   ├── objective.py
│   ├── ollama.py
│   ├── prompts.py
│   ├── security.py
│   ├── state.py
│   ├── supervisor.py
│   ├── tool_registry.py
│   └── workflow.py
├── tools/
│   ├── files.py
│   ├── internet.py
│   └── shell.py
├── tests/
├── .github/workflows/ci.yml
├── CHANGELOG.md
├── CONTRIBUTING.md
├── DEVELOPMENT_SUMMARY.md
├── PERFORMANCE.md
├── SECURITY.md
└── TEST_REPORT.md
```

## Getting started

Start Ollama and make sure the configured model is available:

```bash
ollama run granite-code:3b
```

Then start the agent from the repository root:

```bash
python3 main.py
```

The runtime uses only Python's standard library; there are no required third-party Python packages.

## CLI commands

```text
tools             formatted tool catalog
tool <name>       details for one tool
memory            recent persistent memory
help              command help
exit              exit
```

Examples:

```text
Task> list files of current directory
Task> read_file("README.md")
Task> execute script whoami
Task> read agent/supervisor.py and summarize it in supervisor_summary.txt
```

Simple deterministic requests bypass the model entirely. Literal file creation also bypasses inference, and known-target edit/append tasks use Granite only to generate content while Python owns the destination and tool selection.

## Tools

### Files

- `list_files(path=".", recursive=False)`
- `read_file(path, start_line=1, end_line=800)`
- `write_file(path, content)`
- `append_file(path, content)`

Filesystem tools are confined to the configured workspace. Resolved paths, including symlinks, may not escape it.

### System

- `run_shell(command)`

Shell execution uses `/bin/bash -lc` in the workspace. The controller blocks sensitive operations such as unrequested `sudo`, package-manager execution, filesystem formatting, power operations, destructive root deletion, and destructive Git cleanup/reset operations.

### Network

- `curl_internet(url, timeout=30)`

Only HTTP/HTTPS URLs are accepted. Private, loopback, link-local, reserved, multicast, and unspecified IP targets are blocked by default, including redirect targets. Set `AGENT_ALLOW_PRIVATE_NETWORK=1` only when private-network access is intentionally required.

## Granite-specific communication

Granite Code does not need native Ollama tool calling. It returns one constrained JSON action, for example:

```json
{
  "action": "write_file",
  "arguments": {
    "path": "summary.txt",
    "content": "Generated content"
  }
}
```

The parser tolerates several predictable small-model errors:

- legacy `{"action":"tool","tool":"..."}` wrappers;
- nested `arguments` objects;
- direct top-level tool arguments;
- completion aliases such as `return`, `done`, and `finish`;
- Markdown JSON fences.

Observation echoes and unknown actions are rejected.

## Controller-owned workflows

For compound file transformations, Python owns the state machine:

```text
READ -> TRANSFORM -> WRITE -> VERIFY -> COMPLETE
```

If a source path is explicit, the controller reads it deterministically and paginates automatically. Once the source is complete, file-reading tools are removed from the model's allowed tool set and the next phase is restricted to writing.

After a successful write, the controller performs an independent read-back verification and completes the task without asking Granite to enter another read loop.

For web-to-file transformations:

```text
FETCH -> TRANSFORM -> WRITE -> VERIFY -> COMPLETE
```

Fetched web content satisfies the source-retrieval phase; the controller does not incorrectly request a local file read afterward.

## Context and performance management

The default Ollama context is 16,384 tokens. Real-hardware profiling showed that prompt prefill dominates Granite latency: cache-miss action prompts around 1.4–1.9K tokens took roughly 18–25 seconds, while reused prompt prefixes evaluated in tens of milliseconds. The agent therefore optimizes prompt structure rather than recombining Python modules.

Performance measures include:

- a stable action-prompt prefix to maximize Ollama/llama.cpp prompt-cache reuse;
- only durable facts are sent from persistent memory—completed task answers and old file paths are excluded;
- action selection uses a 96-token output budget by default;
- transformation generation has its own 384-token budget;
- action observations contain metadata rather than full source bodies;
- compound file tasks use a dedicated `Python read -> Granite transform -> Python write/verify` path;
- literal writes, directory listings, shell commands, and default latest-news retrieval bypass action inference;
- non-progress loops abort after three iterations by default;
- oversized transform inputs and tool results are bounded.

See `PERFORMANCE.md` for measured behavior and tuning guidance.

## Testing

Run all unit tests:

```bash
python3 -m unittest discover -s tests -v
```

Compile the complete source tree:

```bash
python3 -m compileall -q .
```

The current release passes **57 unit tests** covering parser normalization, routing, workflow transitions, file confinement, symlink escape protection, shell policy, output truncation, network target validation, compound file workflows, pagination, output-path enforcement, and controller-owned write verification.

GitHub Actions runs both checks on pushes and pull requests.

## Runtime files

Runtime state is intentionally excluded from Git:

- `.agent/`
- `logs/`
- Python bytecode/cache directories
- virtual environments
- `.env` files
- test/build artifacts

## AI-assisted development

This project was developed with assistance from OpenAI's ChatGPT. ChatGPT was used during development for code generation, debugging, architectural refinement, documentation, and analysis of test results. Generated code was reviewed, tested, modified, and integrated by the repository author.

The runtime agent itself does **not** depend on OpenAI services or APIs. It operates locally through Ollama and IBM Granite Code models.

OpenAI and ChatGPT are not affiliated with, sponsors of, or endorsers of this project.

## License

Licensed under the Apache License 2.0. See `LICENSE`.


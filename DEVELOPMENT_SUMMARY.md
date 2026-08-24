# Development Summary --- Ollama Local Granite Code Agent

## Project Overview

This project implements a **local autonomous coding agent** built in
Python and designed specifically for IBM Granite Code models running
through Ollama.

The current implementation has been optimized primarily for:

-   `granite-code:3b`
-   Ollama `0.32.x`
-   Python `3.14.x`
-   Linux / Ubuntu
-   GPU-constrained local inference
-   16,384-token Ollama context
-   Structured autonomous tool execution
-   Multi-step file manipulation and coding workflows

The architecture deliberately avoids dependence on native model
tool-calling capabilities. Granite Code is treated as a **reasoning and
transformation engine**, while deterministic Python code handles tool
execution, workflow enforcement, validation, safety, and state
management.

## Development Motivation

The agent originally evolved from an implementation targeting Qwen
models. Testing on the target hardware showed that Qwen models had
substantially higher inference costs, while `granite-code:3b` provided
significantly faster responses.

Granite Code introduced a different set of challenges:

-   It does not expose Ollama's native `tools` capability.
-   It frequently generates direct tool names instead of wrapper
    actions.
-   Tool arguments may be nested incorrectly.
-   It may echo previous tool results.
-   It sometimes prematurely claims task completion.
-   It may repeatedly read the same file instead of progressing to a
    write operation.
-   Small Granite models can have difficulty maintaining a multi-step
    state machine solely through prompting.
-   Responses are not always valid JSON.
-   `return`, `done`, `finish`, and similar actions may be generated
    instead of the expected completion action.

The architecture was consequently redesigned around the principle:

> **Granite decides what content or transformation is required; Python
> controls how the task progresses.**

## Current Architecture

The application is modular rather than implemented as a single large
supervisor script.

``` text
ollama-local-agent-granite-code/
│
├── main.py
├── agent/
│   ├── __init__.py
│   ├── config.py
│   ├── logging_setup.py
│   ├── memory.py
│   ├── ollama.py
│   ├── prompts.py
│   ├── state.py
│   ├── supervisor.py
│   └── tool_registry.py
├── tools/
│   ├── __init__.py
│   ├── files.py
│   ├── shell.py
│   └── internet.py
└── tests/
    └── ...
```

Responsibilities are deliberately separated between model communication,
orchestration, state management, tool registration, and actual tool
implementations.

## Supervisor

`agent/supervisor.py` is the central orchestration component.

The supervisor is responsible for:

-   task lifecycle management;
-   Granite response parsing;
-   malformed JSON recovery;
-   action normalization;
-   tool argument normalization;
-   task requirement detection;
-   deterministic routing of simple operations;
-   tool permission enforcement;
-   loop detection;
-   duplicate-action prevention;
-   paginated file reads;
-   output-file detection;
-   write verification;
-   completion validation;
-   iteration limits;
-   tool-call limits;
-   interactive iteration interrupts;
-   user-visible tool output;
-   persistent task completion.

The supervisor therefore acts as the deterministic control plane around
the probabilistic model.

## Granite Action Normalization

One of the major compatibility improvements was allowing Granite to emit
its natural action structure.

Instead of requiring only:

``` json
{
  "action": "tool",
  "tool": "read_file",
  "arguments": {
    "path": "agent/supervisor.py"
  }
}
```

the controller accepts the simpler Granite output:

``` json
{
  "action": "read_file",
  "arguments": {
    "path": "agent/supervisor.py"
  }
}
```

Aliases such as `done`, `finish`, `finished`, `final`, `return`,
`respond`, and `response` can also be interpreted as completion
requests.

This substantially reduces failures caused by imposing a protocol that
small Granite models do not reliably follow.

## Nested Argument Repair

Testing revealed Granite responses such as:

``` json
{
  "action": "read_file",
  "arguments": {
    "arguments": {
      "path": "agent/supervisor.py"
    }
  }
}
```

This previously caused errors such as:

``` text
TypeError: FileTools.read_file() got an unexpected keyword argument 'arguments'
```

The supervisor now recursively unwraps redundant `arguments` containers
before invoking a tool.

## Deterministic Tool Routing

Simple requests no longer require an LLM round trip.

Examples include:

``` text
read_file(agent/supervisor.py)
list_files(".")
list current directory
execute script whoami
```

These requests can be recognized and executed directly by Python,
providing lower latency, reduced token usage, fewer malformed Granite
actions, deterministic behavior, and reduced context consumption.

## Python-Generated Tool Catalog

The `tools` command and tool metadata are generated directly from the
Python tool registry.

The model is no longer asked to enumerate available tools. This avoids
unnecessary inference and prevents Granite from hallucinating, omitting,
or incorrectly describing tools.

## Phase-Specific Tool Permissions

A major architectural change was introducing controller-enforced
workflow phases.

For a task such as:

``` text
Read agent/supervisor.py, summarize its workings,
and save the summary to supervisor_summary.txt
```

the intended workflow becomes:

``` text
READ
  ↓
TRANSFORM
  ↓
WRITE
  ↓
VERIFY
  ↓
COMPLETE
```

During the read phase, the available tools can be restricted to
`read_file` and `list_files`. Once reading is complete, `read_file` is
removed from the allowed set and the model receives appropriate writing
operations such as `write_file` and `append_file`.

This addresses one of the most persistent Granite Code 3B problems:
repeatedly reading a source file without progressing to output
generation.

## Task Requirement Detection

The supervisor performs lightweight analysis of the user's objective
before invoking the model. It determines whether the task requires
reading, writing, or internet access.

The controller refuses completion until all required operations have
succeeded.

## Output Path Detection

The supervisor attempts to derive output filenames directly from the
task. If Granite generates a `write_file` action without a path, the
controller can inject the detected output path.

This reduces reliance on the model correctly carrying filenames across
several iterations.

## Completion Validation

Granite is no longer trusted to decide unilaterally that a task has
finished.

A completion request is rejected if mandatory workflow steps remain
outstanding. For example, if the objective requires a file to be written
but no successful `write_file` or `append_file` operation has occurred,
the controller rejects completion and instructs Granite to continue.

## Controller-Owned Write Verification

Successful file creation is verified independently by the controller.

After `write_file` or `append_file` succeeds, Python performs a
read-back of the generated file. The model therefore does not need to
initiate another verification read itself.

A verified write can terminate the task deterministically.

## Paginated File Reading

Large source files can exceed the safe amount of content for one tool
result.

`read_file` therefore supports paginated reads. If a result indicates
`has_more: true` and provides `next_line`, the controller can
automatically advance the subsequent read to the next section.

The workflow only considers reading complete once the final page has
been retrieved.

## Context Management

The target Ollama runtime has been tested with a 16,384-token context.

The agent limits the amount of tool output retained in active model
context. Large fields such as `content`, `body`, `stdout`, and `stderr`
are truncated before being retained indefinitely.

Prompt size is also bounded by a configurable maximum context-character
budget.

This is intended to prevent context overflow, excessive
prompt-evaluation latency, degraded Granite behavior, and accidental
reproduction of entire previous tool results.

## Observation Handling

Tool results are stored as observations in `TaskState`.

The model can therefore reason over previously retrieved information
without rerunning the same tool.

The key distinction is:

``` text
tool result = evidence
tool result ≠ new instruction
```

The controller also rejects responses that appear to be echoed
observations rather than new actions.

## Loop Detection

Several forms of looping were observed during testing, particularly
repeated `read_file` calls.

The current implementation provides multiple safeguards:

-   identical non-progressing tool calls can be blocked;
-   repeated identical model actions are detected independently;
-   phase-specific tool restrictions prevent Granite from returning to a
    completed workflow phase;
-   loop detection generates a fresh controller instruction identifying
    the next required operation.

## Shell Execution

The agent supports shell execution through `run_shell`.

Additional policy checks block potentially destructive or privileged
commands unless the task explicitly requires them, including operations
involving `sudo`, package managers, filesystem formatting,
shutdown/reboot operations, and destructive recursive deletion.

## Internet Access

Internet retrieval is available through the `curl_internet` tool.

This allows the local agent to retrieve web pages, RSS feeds, APIs,
documentation, and current information.

For tasks requiring both retrieval and file generation, the workflow
becomes:

``` text
FETCH
  ↓
TRANSFORM
  ↓
WRITE
  ↓
VERIFY
  ↓
COMPLETE
```

## Interactive Iteration Interrupt

Between autonomous iterations, the supervisor provides an interactive
control point:

``` text
[Enter]=continue | stop | state | instruction [auto-continue in 3s]>
```

If no input is received within three seconds, execution automatically
continues.

The operator can press Enter to continue immediately, enter `stop`,
inspect `state`, or provide an additional instruction.

## Logging

Each agent startup creates a unique timestamped logfile in the project
directory.

Logs capture startup configuration, Python version, Ollama connectivity,
selected model, context configuration, task/session ID, workflow phase,
iteration count, model response latency, raw model responses at debug
level, tool calls, tool arguments, tool results, controller decisions,
blocked actions, completion verification, and exceptions.

## Memory

Persistent memory is maintained separately from active task state.

The memory layer stores selected information such as completed tasks,
previously changed files, and recent relevant history. Memory is
deliberately bounded to avoid continuously increasing model context.

## Testing

The development process introduced unit testing for the agent's tools
and controller behavior.

Important test targets include:

-   file listing;
-   file reading;
-   file writing;
-   append operations;
-   path validation;
-   shell execution;
-   internet retrieval;
-   tool registry dispatch;
-   malformed arguments;
-   invalid tool names;
-   duplicate actions;
-   task-state recording;
-   completion enforcement;
-   Granite action normalization.

## Key Issues Resolved

Development iterations addressed concrete failures including:

``` text
NameError: ensure_workspace is not defined
ModuleNotFoundError: requests
ModuleNotFoundError: No module named 'agent'
Supervisor.__init__() got an unexpected keyword argument 'config'
FileTools.read_file() got an unexpected keyword argument 'arguments'
INVALID GRANITE ACTION
action must be 'tool' or 'complete'
action must be a valid tool name or 'complete'
INVALID GRANITE JSON
PermissionError: Path outside workspace
```

Additional behavioral issues addressed include agent termination after
successful direct tasks, missing actual tool output, repeated
source-file reads, premature completion, missing output-file creation,
endless replanning, duplicated tool arguments, model-generated tool
enumeration, and excessive dependence on the LLM for deterministic
operations.

## Architectural Conclusion

A central result of development is that the limitations encountered with
`granite-code:3b` do **not** require abandoning the model.

The more effective approach is to reduce the amount of orchestration
delegated to it.

The resulting responsibility split is:

``` text
┌─────────────────────────────────────────────┐
│               Python Controller             │
├─────────────────────────────────────────────┤
│ Task analysis                               │
│ Workflow state                              │
│ Tool discovery                              │
│ Tool permissions                            │
│ Tool execution                              │
│ Argument normalization                      │
│ Pagination                                  │
│ Loop detection                              │
│ Safety policy                               │
│ Verification                                │
│ Completion enforcement                      │
│ Persistent state                            │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│              Granite Code Model             │
├─────────────────────────────────────────────┤
│ Reasoning                                   │
│ Code understanding                          │
│ Code generation                             │
│ Summarization                               │
│ Transformation                              │
│ Selecting among currently permitted actions │
└─────────────────────────────────────────────┘
```

This makes a relatively small local model substantially more useful as
an autonomous development component.

## Current Development Status

The project has progressed from a monolithic Qwen-oriented autonomous
loop into a modular, Granite-specific local agent architecture.

The current focus is no longer merely making Granite produce
syntactically valid tool calls. The controller now compensates for
predictable small-model weaknesses and actively drives tasks toward
verified outcomes.

The most important current design principle is:

> **Use the LLM for decisions and transformations that require an LLM;
> use deterministic Python for everything that does not.**

This should remain the guiding principle for subsequent development of
the repository.

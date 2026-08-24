# ollama-local-agent-granite-code
This repository is concerned with the creation to drive a locally running llm module with a self created python agent, using ollama and granite-code:3b on a vulkan GPU

**Background:**
I have found an old AMD FirePro S7150 GPU (2016) cheaply with 8GB VRAM and was keen to experiment with locally running llm models.
CPU: AMD Ryzen 9 5950X / RAM: 64GB
The aim was to read files locally for further analysis, without the need to upload those.

**Process Overview:**
- experimentation with a few unix versions, because the native driver support for the AMD FirePro has ended, hence experimenting with Ubuntu 20.04.2 and SUSE 15 SP2, but both releases have had compatibility issues to run the native driver, finally settled on Ubuntu 26.04 with mesa-radv driver. 
- to drive the llm a local agent is required, but e.g. CrewAI does not support latest Python V3.14.4, hence decided to develop the agent
- first version was a simple call in a Python program, this continuously evolved into a small project, which still has to be finalized

**Results:**
- the FirePro is able to run a qwen3.5:9b model, with a context of up to 32k but it quickly runs into overheating issue (about 12 sec).
- generation speed for qwen3.5:9b with 32k context is about 16 token/s, with 16k context about 19 token/s but require external cooling, which is why the approach to get the largest possible model into the GPU has been abandoned
- code quality with local llm models has not been satisfactory, hence experimentation with thinking models like gemma4:4b, qwen3.5:8b, or llama3.1:8b was stopped, nevertheless the hardware was able to fit the models
- switching to non-thinking models, e.g. granite-code:8b or granite-code:3b has been expected to be beneficial. The issue with these models has been that the code quality is even worse, but at least they produced output at a reasonable speed.
- generation speed for granite-code:8b with 16k context has been 23 token/s, for granite-code:3b with 16k context the has been **49 token/s** 
- the first code was one large python file, to which logging and unit testing have been added for debugging purposes, but which has ultimately been rewritten in a modular manner
- in the end the agent was optimized for granite-code:3b with 16k context, exposing the following tools to the model:

========================================================================
 AVAILABLE TOOLS
========================================================================

FILES
  append_file(path: 'str', content: 'str') -> 'dict[str, Any]'
      Append text to a file; use only when append semantics are required.
  list_files(path: 'str' = '.', recursive: 'bool' = False) -> 'dict[str, Any]'
      List files/directories inside the workspace.
  read_file(path: 'str', start_line: 'int' = 1, end_line: 'int' = 800) -> 'dict[str, Any]'
      Read a UTF-8 text file with optional line range.
  write_file(path: 'str', content: 'str') -> 'dict[str, Any]'
      Create or replace a text file.

NETWORK
  curl_internet(url: 'str', timeout: 'int' = 30) -> 'dict[str, Any]'
      Fetch an HTTP/HTTPS URL.

SYSTEM
  run_shell(command: 'str') -> 'dict[str, Any]'
      Run a shell command from the workspace.

Use a tool by describing the task normally; direct commands such as
read_file(path) and list_files(.) are routed without an LLM call.
========================================================================

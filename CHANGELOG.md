# Changelog

## 0.3.0 — Performance and workflow reliability

- diagnosed real-hardware latency as Granite prompt-prefill cost rather than Python module dispatch;
- reduced action-selection prompt size and created a stable prefix for Ollama/llama.cpp prompt-cache reuse;
- separated action generation (`96` tokens default) from content transformation (`384` tokens default);
- removed completed task answers and changed-file history from automatic model prompt memory;
- added deterministic route for `list files of the working directory`;
- added deterministic literal file creation without an LLM call;
- added deterministic default RSS news retrieval and Python headline extraction;
- changed known-target append/edit tasks so Python owns the tool and output path while Granite generates content only;
- changed source-summary workflows to Python read → Granite transform → Python write → Python verify;
- restricted append objectives to `append_file` and normal write objectives to `write_file`;
- added early abort for repeated non-progressing model actions;
- enabled Ollama JSON mode for controller actions;
- removed huge Ollama context-token arrays from debug logs and added prompt/evaluation timing metrics;
- expanded test suite to 57 tests;
- added `PERFORMANCE.md` and updated development/test documentation.

# Contributing

1. Create a feature branch.
2. Keep tool functions deterministic and return dictionaries containing `ok`.
3. Preserve workspace path restrictions for filesystem tools.
4. Run the unit tests before committing:

```bash
python -m unittest discover -s tests -v
```

5. Keep Ollama/model calls out of unit tests unless a test is explicitly marked as an integration test.

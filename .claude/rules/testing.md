# Testing Rules
- Command: `py -3.12 -m pytest [path] -q`
- Every tool needs: success, invalid input, missing file, error propagation tests
- Mock ALL external calls (Resolve, ComfyUI, YouTube API, filesystem services)
- Test count must NOT decrease after changes
- Targeted changes → run specific suite. Before commit → full suite.
- Use `pytest.mark.skipif` for tests requiring live services (Resolve, ComfyUI, Ollama)

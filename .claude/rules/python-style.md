# Python Style Rules
- Type hints on ALL function signatures
- Docstrings on ALL public functions
- async/await for ALL I/O operations
- Error → fallback, not crash. Never bare `except:`
- JSON-serializable outputs on all tool returns
- Import order: stdlib → third-party → local
- f-strings over .format() or %

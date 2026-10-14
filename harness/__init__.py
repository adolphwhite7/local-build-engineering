"""M2 walking-skeleton harness modules.

Implements a bounded local-first pipeline: load one approved example
file, split it into paragraph-first passages, send at most three of
them to the pinned local Ollama model, verify the structured response,
and report the result in R10 vocabulary.
"""

__version__ = "M2"

"""The literature tool: PDF text (text.py), the name finder (finder.py), staging and applying
(stage.py). Driven by the /ingest-literature skill on the data machine (docs/REFACTOR.md)."""

from .finder import GERMAN_ENGLISH, ISLANDS, LATIN_STOP

__all__ = ["GERMAN_ENGLISH", "ISLANDS", "LATIN_STOP"]

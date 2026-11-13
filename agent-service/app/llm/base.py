from typing import Protocol


class ExplanationProvider(Protocol):
    def explain(self, category: str) -> str: ...

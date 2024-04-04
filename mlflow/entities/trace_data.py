from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from mlflow.entities.span import Span


@dataclass
class TraceData:
    """A container object that holds the spans data of a trace.

    Args:
        spans: List of spans that are part of the trace.
    """

    spans: List[Span] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d) -> "TraceData":
        return cls(spans=[Span.from_dict(s) for s in d.get("spans", [])])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

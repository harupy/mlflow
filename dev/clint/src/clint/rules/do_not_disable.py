from typing_extensions import Self

from clint.rules.base import Rule


class DoNotDisable(Rule):
    DO_NOT_DISABLE = {
        "B006": "Default to `None` and assign the value inside the function body.",
        "F821": (
            "For errors on forward references, use `typing.TYPE_CHECKING` to avoid runtime "
            "import errors."
        ),
    }

    def __init__(self, rules: set[str]) -> None:
        self.rules = rules

    @classmethod
    def check(cls, rules: set[str]) -> Self | None:
        if s := rules.intersection(DoNotDisable.DO_NOT_DISABLE):
            return cls(s)
        return None

    def _message(self) -> str:
        hints = {
            "B006": "Default to `None` and assign the value inside the function body.",
            "F821": (
                "For forward reference errors, use `typing.TYPE_CHECKING` to avoid runtime "
                "import errors."
            ),
        }
        return "NEVER DISABLE THE FOLLOWING RULES: " + ", ".join(
            f"{rule} ({hints[rule]})" for rule in sorted(self.rules)
        )

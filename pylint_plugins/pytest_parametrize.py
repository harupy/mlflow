import astroid
from pylint.interfaces import IAstroidChecker
from pylint.checkers import BaseChecker


class PytestParametrize(BaseChecker):
    __implements__ = IAstroidChecker

    name = "pytest-parametrize"
    PREFER_TUPLE = "pytest-parametrize-prefer-tuple"
    msgs = {
        "W0005": (
            "Use tuple instead of comma-separated string. For example: 'a,b' -> ('a', 'b')",
            PREFER_TUPLE,
            "Use tuple",
        ),
    }
    priority = -1

    def visit_call(self, node: astroid.Call):
        if node.func.as_string() == "pytest.mark.parametrize":
            first_arg = node.args[0]
            if (
                isinstance(first_arg, astroid.Const)
                and isinstance(first_arg.value, str)
                and "," in first_arg.value
            ):
                self.add_message(self.PREFER_TUPLE, node=node)

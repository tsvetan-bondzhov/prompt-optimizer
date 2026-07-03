"""Reference ``prepare_evaluation()`` factory (Task 07).

``prepare_evaluation`` is the user-supplied factory that returns the *ordered*
list of concrete :class:`EvaluationStep` instances the evaluator should run for
each evaluation point. It conforms to the
:class:`~app.core.interfaces.PrepareEvaluation` protocol (a zero-argument
callable returning ``list[EvaluationStep]``).

It is registered under ``("evaluation_prepare", "default")`` so that, with the
default settings (``ACTIVE_EXECUTOR="default"``),
:func:`app.core.registry.get_evaluation_steps` resolves to it. The executor and
its matching evaluation steps form a paired set keyed off ``ACTIVE_EXECUTOR``.

To customize: reorder, add, or remove steps below, or register your own factory
under a different name and point ``ACTIVE_EXECUTOR`` at it.
"""

from __future__ import annotations

from app.core.interfaces import EvaluationStep
from app.core.registry import register
# from app.implementations.evaluation_steps import (
#     KeywordCoverageStep,
#     ResponseQualityStep,
# )
from app.implementations.json_evaluation_steps import (
    JsonExpectedMatchStep,
    JsonSchemaValidationStep,
)

__all__ = ["prepare_evaluation"]


def prepare_evaluation() -> list[EvaluationStep]:
    """Return the ordered list of evaluation steps for the default executor."""

    # >>> USER: add / remove / reorder your evaluation steps here. <<<
    return [
        JsonSchemaValidationStep(),
        JsonExpectedMatchStep(),
    ]


# Register the factory itself (not an instance) under the default name. The
# registry's ``get_evaluation_steps`` resolves this entry by *calling* the
# factory, which returns fresh step instances each time.
register("evaluation_prepare", "default", prepare_evaluation)

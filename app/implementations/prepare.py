"""Reference ``prepare_graders()`` factory (Task 07).

``prepare_graders`` is the user-supplied factory that returns the *ordered*
list of concrete :class:`Grader` instances the evaluator should run for
each evaluation point. It conforms to the
:class:`~app.core.interfaces.PrepareGraders` protocol (a zero-argument
callable returning ``list[Grader]``).

It is registered under ``("grader_prepare", "default")`` so that, with the
default settings (``ACTIVE_EXECUTOR="default"``),
:func:`app.core.registry.get_graders` resolves to it. The executor and
its matching graders form a paired set keyed off ``ACTIVE_EXECUTOR``.

To customize: reorder, add, or remove steps below, or register your own factory
under a different name and point ``ACTIVE_EXECUTOR`` at it.
"""

from __future__ import annotations

from app.core.interfaces import Grader
from app.core.registry import register
# from app.implementations.graders import (
#     KeywordCoverageGrader,
#     ResponseQualityGrader,
# )
from app.implementations.json_graders import (
    JsonExpectedMatchGrader,
    JsonSchemaValidationGrader,
)

__all__ = ["prepare_graders"]


def prepare_graders() -> list[Grader]:
    """Return the ordered list of graders for the default executor."""

    # >>> USER: add / remove / reorder your graders here. <<<
    return [
        JsonSchemaValidationGrader(),
        JsonExpectedMatchGrader(),
    ]


# Register the factory itself (not an instance) under the default name. The
# registry's ``get_graders`` resolves this entry by *calling* the
# factory, which returns fresh step instances each time.
register("grader_prepare", "default", prepare_graders)

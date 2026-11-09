"""Saved templates: a named plan that pre-fills the Configure wizard. Never holds a secret."""

from typing import Annotated

from pydantic import Field, StringConstraints

from .common import StrictModel
from .plan import ConfigPlan, NoteText

TemplateName = Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9 _.()-]+$")]
OsId = Annotated[str, StringConstraints(max_length=40, pattern=r"^[a-z0-9_]+$")]


class TemplateCreate(StrictModel):
    name: TemplateName
    description: NoteText = ""
    os_id: OsId | None = None  # None: any OS (the plan is OS-neutral; the driver turns it into commands)
    plan: ConfigPlan


class TemplateUpdate(StrictModel):
    name: TemplateName | None = None
    description: NoteText | None = None
    os_id: OsId | None = Field(default=None)
    plan: ConfigPlan | None = None

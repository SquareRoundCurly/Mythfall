import json
from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    script: str | None = None
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    handoffs: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=20, ge=1)

    @classmethod
    def from_json_file(cls, path: Path) -> "AgentConfig":
        with path.open(encoding="utf-8") as config_file:
            return cls.model_validate(json.load(config_file))

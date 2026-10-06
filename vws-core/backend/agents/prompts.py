"""GD-02: load the four amended, versioned prompt files and bind their bytes."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from backend.core.errors import ConfigurationError

PROMPT_NAMES = frozenset(
    {"news_sentiment", "research_synthesis", "head_of_desk", "fundamental_analyst"}
)
_SECTIONS = ("Role", "Input schema", "Output JSON schema", "Rules", "Injection defense")
PROMPT_DIRECTORY = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: str
    text: str
    prompt_hash: str


def load_prompt(name: str, directory: Path = PROMPT_DIRECTORY) -> Prompt:
    """Only inventory names are accepted; malformed or indirect files fail closed."""
    if name not in PROMPT_NAMES:
        raise ConfigurationError("GD-02: unknown prompt name")
    try:
        path = directory / (name + ".md")
        if path.is_symlink() or directory.resolve() != directory.absolute():
            raise ValueError("indirect prompt path")
        raw = path.read_bytes()
        if not 64 <= len(raw) <= 65_536:
            raise ValueError("unbounded prompt")
        text = raw.decode("utf-8")
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError("missing front matter")
        front = yaml.safe_load(parts[1])
        if not isinstance(front, dict) or set(front) != {"version"}:
            raise ValueError("invalid prompt front matter")
        version = front["version"]
        if not isinstance(version, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", version):
            raise ValueError("missing prompt version")
        if any(
            re.search(r"(?m)^# " + section + r"\s*$", parts[2]) is None for section in _SECTIONS
        ):
            raise ValueError("missing required prompt section")
        return Prompt(name, version, text, hashlib.sha256(raw).hexdigest())
    except Exception:
        raise ConfigurationError("GD-02: prompt could not be verified") from None

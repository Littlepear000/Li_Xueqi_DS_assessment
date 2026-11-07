"""Runtime settings shared by the CLI, the notebook and the web app.

Everything the pipeline needs to know about *where things are* lives here, so
that the workflow code itself never hard-codes a path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _dotenv_value(key: str) -> str | None:
    """Read KEY=value from a .env file in the current directory or its parents (no dependency on python-dotenv)."""
    here = Path.cwd()
    for folder in [here, *here.parents]:
        f = folder / ".env"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


PROVIDERS = {
    # provider -> (default model, default base URL for OpenAI-compatible chat completions, env var holding the key)
    "anthropic": ("claude-sonnet-4-5", "", "ANTHROPIC_API_KEY"),
    "deepseek": ("deepseek-flash", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "openai": ("gpt-4.1-mini", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "mock": ("mock", "", ""),
}


@dataclass
class LLMSettings:
    """How to call the language model.

    ``provider`` is one of
      - ``"anthropic"``  Anthropic Messages API (prompt caching on the system prompt)
      - ``"deepseek"``   DeepSeek, OpenAI-compatible chat completions (thinking disabled, JSON mode)
      - ``"openai"``     any OpenAI-compatible endpoint (set ``base_url`` / ``LLM_BASE_URL``)
      - ``"mock"``       deterministic canned answers for tests and for the UI without a key
    The key is read from the provider's environment variable or from a ``.env`` file.
    """

    provider: str = "anthropic"
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 4000
    temperature: float = 0.0
    max_input_chars: int = 160_000  # hard cap on document text passed per call
    # Token saving (none of these changes a prompt or a workflow step):
    step_models: dict = field(default_factory=dict)  # per-step model override, e.g. {"codes": "claude-haiku-4-5", "merge": "claude-haiku-4-5"}; same provider
    response_cache: bool = False   # reuse a stored answer when exactly the same request (model, system, prompt) was answered before
    response_cache_dir: Path | None = None   # set by Settings to <output>/cache/llm when left empty
    warm_cache: bool = True        # send the first call with a given system prompt alone, so parallel calls read the prompt cache instead of all writing it

    def model_for(self, step: str) -> str:
        return self.step_models.get(step) or self.model

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown LLM provider {self.provider!r}; choose from {', '.join(PROVIDERS)}")
        default_model, default_url, env_key = PROVIDERS[self.provider]
        if not self.model:
            self.model = default_model
        if self.base_url is None:
            self.base_url = os.environ.get("LLM_BASE_URL") or _dotenv_value("LLM_BASE_URL") or default_url
        if self.api_key is None and env_key:
            self.api_key = os.environ.get(env_key) or _dotenv_value(env_key) or os.environ.get("LLM_API_KEY") or _dotenv_value("LLM_API_KEY")

    @property
    def key_env_var(self) -> str:
        return PROVIDERS[self.provider][2]


@dataclass
class Settings:
    """Paths and options for one pipeline run."""

    raw_dir: Path
    output_dir: Path
    documents_dirs: list[Path] = field(default_factory=list)
    projects_csv: Path | None = None
    workflow: str = "v1"
    llm: LLMSettings = field(default_factory=LLMSettings)
    debug: bool = False          # keep raw LLM exchanges and verbose step output next to each record
    workers: int = 16            # parallel projects in run_batch (API limits allow far more than this)
    acquire: bool = True         # during a run, fetch a project's missing documents from the WBG API into output/supplement_documents

    def __post_init__(self) -> None:
        self.raw_dir = Path(self.raw_dir)
        self.output_dir = Path(self.output_dir)
        if self.projects_csv is None:
            self.projects_csv = self.raw_dir / "projects.csv"
        if not self.documents_dirs:
            # Local corpus (raw_data/documents) + documents fetched from the WBG API during runs
            # (output/supplement_documents). Legacy api_supplement folder under raw_data is still read if present.
            self.documents_dirs = [self.raw_dir / "documents", self.output_dir / "supplement_documents"]
            legacy = self.raw_dir / "api_supplement" / "documents"
            if legacy.exists():
                self.documents_dirs.append(legacy)
        self.documents_dirs = [Path(p) for p in self.documents_dirs]
        if os.environ.get("PIAA_ACQUIRE", "").strip() in ("0", "false", "no"):
            self.acquire = False
        if self.llm.response_cache and self.llm.response_cache_dir is None:
            self.llm.response_cache_dir = self.output_dir / "cache" / "llm"

    @property
    def cache_dir(self) -> Path:
        return self.output_dir / "cache"

    @property
    def runs_dir(self) -> Path:
        return self.output_dir / "runs"

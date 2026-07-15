"""
ODIN Memory — Settings
=======================
Single source of truth for paths, ports, and config file locations.
Everything else (providers, models) lives in config/providers.json —
NOT here — so switching providers never means editing code.

Override any of these via a .env file placed at ODIN_ROOT/.env,
or via real environment variables (env vars win).
"""

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings

# ODIN_ROOT defaults to the memory_pro directory inside the current project.
# Override with the ODIN_ROOT env var if you keep it somewhere else.
_THIS_DIR = Path(__file__).resolve().parent   # memory_pro/
DEFAULT_ROOT = Path(os.environ.get("ODIN_ROOT", str(_THIS_DIR)))


class Settings(BaseSettings):
    # ── Identity ───────────────────────────────────────────────
    odin_name: str = "ODIN"
    odin_version: str = "3.0.0"
    odin_built_by: str = "Charles"

    # ── Server ─────────────────────────────────────────────────
    host: str = "0.0.0.0"
# Memory Pro standard port across the full ODIN stack
    port_memory: int = 8010
    debug: bool = True

    # ── Root path (Fedora-native, not Windows) ────────────────
    odin_root: Path = DEFAULT_ROOT

    class Config:
        # Check memory_pro/.env, then project root .env, then system env
        env_file = str(DEFAULT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    # ── Derived paths ──────────────────────────────────────────
    @property
    def data_dir(self) -> Path:
        return self.odin_root / "data"

    @property
    def raw_store_dir(self) -> Path:
        return self.odin_root / "layers" / "layer1_raw" / "raw_store"

    @property
    def longterm_file(self) -> Path:
        return self.odin_root / "layers" / "layer2_longterm" / "long_term_memory.json"

    @property
    def graph_file(self) -> Path:
        return self.odin_root / "layers" / "layer3_knowledge" / "knowledge_graph.json"

    @property
    def summaries_dir(self) -> Path:
        return self.odin_root / "layers" / "layer4_summaries" / "daily_summaries"

    @property
    def identity_file(self) -> Path:
        return self.odin_root / "identity" / "identity_profile.json"

    @property
    def providers_config_file(self) -> Path:
        return self.odin_root / "config" / "providers.json"

    def ensure_dirs(self) -> None:
        for d in [self.data_dir, self.raw_store_dir, self.longterm_file.parent,
                  self.graph_file.parent, self.summaries_dir, self.identity_file.parent,
                  self.providers_config_file.parent]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


if __name__ == "__main__":
    s = get_settings()
    print(f"ODIN_ROOT:       {s.odin_root}")
    print(f"port_memory:     {s.port_memory}")
    print(f"raw_store_dir:   {s.raw_store_dir}")
    print(f"longterm_file:   {s.longterm_file}")
    print(f"graph_file:      {s.graph_file}")
    print(f"summaries_dir:   {s.summaries_dir}")
    print(f"identity_file:   {s.identity_file}")
    print(f"providers_config:{s.providers_config_file}")

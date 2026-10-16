"""Configuration: pydantic schema + YAML loader."""

from wildfire_kz.config.loader import config_section_hash, dump_config, load_config
from wildfire_kz.config.schema import Config

__all__ = ["Config", "config_section_hash", "dump_config", "load_config"]

"""配置加载模块。

支持从 ``config.yaml`` 或环境变量 ``LOCAL_DATASOURCE_CONFIG`` 读取配置；
若未提供配置文件，则使用默认配置。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class YahooConfig:
    """Yahoo/yfinance 相关配置。"""
    enabled: bool = True
    # 默认使用 akshare；yfinance 仅作为备选（当前网络下 Yahoo 容易限流）
    use_yfinance: bool = False


@dataclass
class ProvidersConfig:
    """所有 provider 的配置聚合。"""
    yahoo: YahooConfig = field(default_factory=YahooConfig)


@dataclass
class Config:
    """全局配置对象。"""
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)


def _merge_defaults(data: dict[str, Any]) -> Config:
    """用用户配置覆盖默认值，返回完整的 Config 对象。"""
    yahoo = YahooConfig(**data.get("providers", {}).get("yahoo", {}))
    return Config(providers=ProvidersConfig(yahoo=yahoo))


def load_config(path: str | None = None) -> Config:
    """加载配置文件。

    参数:
        path: 配置文件路径。为 None 时依次尝试 ``config.yaml``、
              环境变量 ``LOCAL_DATASOURCE_CONFIG``；都找不到则返回默认配置。
    """
    if path is None:
        candidate = Path("config.yaml")
        if candidate.exists():
            path = str(candidate)
        else:
            env_path = os.environ.get("LOCAL_DATASOURCE_CONFIG")
            path = env_path

    if not path or not Path(path).exists():
        return _merge_defaults({})

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _merge_defaults(raw)

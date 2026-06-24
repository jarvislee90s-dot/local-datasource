# tests/test_config.py
from local_datasource.config import load_config

def test_load_default_config():
    cfg = load_config(None)
    assert cfg.providers.yahoo.enabled is True
    assert cfg.providers.yahoo.use_yfinance is False

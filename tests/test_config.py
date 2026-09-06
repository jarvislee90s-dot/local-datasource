# tests/test_config.py
from local_datasource.config import _merge_defaults, load_config

def test_load_default_config():
    cfg = load_config(None)
    assert cfg.providers.yahoo.enabled is True
    assert cfg.providers.yahoo.use_yfinance is False

def test_cache_default():
    """无 cache 段时使用内置默认目录。"""
    cfg = _merge_defaults({})
    assert cfg.cache.data_dir == "./datasource-cache"

def test_cache_data_dir_loaded_from_yaml(tmp_path):
    """yaml 提供 cache.data_dir 时加载之;缺省时回落默认。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "providers:\n  yahoo:\n    use_yfinance: false\ncache:\n  data_dir: ./my-cache\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_file))
    assert cfg.cache.data_dir == "./my-cache"
    assert cfg.providers.yahoo.use_yfinance is False

def test_cache_missing_section_falls_back_to_default(tmp_path):
    """yaml 无 cache 段(以及空值 cache:)时使用默认,不报错。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("providers:\n  yahoo:\n    use_yfinance: false\n", encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.cache.data_dir == "./datasource-cache"

    empty_cache = tmp_path / "empty.yaml"
    empty_cache.write_text("cache:\n", encoding="utf-8")
    assert load_config(str(empty_cache)).cache.data_dir == "./datasource-cache"

# -*- coding: utf-8 -*-
"""TTL-кэш inference_server_reachable."""

import importlib
from unittest.mock import patch

_cfg = importlib.import_module("config.settings")


def test_inference_reachable_uses_cache():
    _cfg._INFERENCE_REACHABLE_CACHE = None
    with patch.object(
        _cfg,
        "_inference_server_reachable_uncached",
        return_value=True,
    ) as mock_uncached:
        assert _cfg.inference_server_reachable(use_cache=True) is True
        assert _cfg.inference_server_reachable(use_cache=True) is True
        mock_uncached.assert_called_once()

    _cfg._INFERENCE_REACHABLE_CACHE = None


def test_inference_reachable_bypass_cache():
    _cfg._INFERENCE_REACHABLE_CACHE = None
    with patch.object(
        _cfg,
        "_inference_server_reachable_uncached",
        return_value=False,
    ) as mock_uncached:
        _cfg.inference_server_reachable(use_cache=False)
        _cfg.inference_server_reachable(use_cache=False)
        assert mock_uncached.call_count == 2

    _cfg._INFERENCE_REACHABLE_CACHE = None

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.config import load_config


class ConfigTests(unittest.TestCase):
    def test_default_context_is_16384(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
        self.assertEqual(config.num_ctx, 16384)
        self.assertEqual(config.model, "granite-code:3b")

    def test_invalid_integer_is_rejected(self) -> None:
        with patch.dict(os.environ, {"AGENT_NUM_CTX": "not-an-int"}, clear=False):
            with self.assertRaises(ValueError):
                load_config()

    def test_private_network_flag(self) -> None:
        with patch.dict(os.environ, {"AGENT_ALLOW_PRIVATE_NETWORK": "true"}, clear=False):
            self.assertTrue(load_config().allow_private_network)

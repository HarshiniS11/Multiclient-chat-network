
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdn.policies import (
    block_client,
    unblock_client,
    is_blocked,
    get_blocked_clients,
)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.ip = "10.0.0.99"
        unblock_client(self.ip)

    def tearDown(self):
        unblock_client(self.ip)

    def test_not_blocked_initially(self):
        self.assertFalse(is_blocked(self.ip))

    def test_block_client(self):
        block_client(self.ip)
        self.assertTrue(is_blocked(self.ip))

    def test_unblock_client(self):
        block_client(self.ip)
        unblock_client(self.ip)
        self.assertFalse(is_blocked(self.ip))

    def test_blocked_clients_snapshot(self):
        block_client(self.ip)
        self.assertIn(self.ip, get_blocked_clients())


if __name__ == "__main__":
    unittest.main()

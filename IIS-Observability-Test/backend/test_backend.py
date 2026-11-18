"""Checks that a real database outage is visible to IIS monitoring."""

import json
import unittest
from unittest.mock import patch

import app


class HealthTests(unittest.TestCase):
    def test_database_outage_returns_503(self):
        with patch.object(app.database, "read_count", side_effect=RuntimeError("database down")):
            response = app.health()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body), {"api": "ok", "database": "unavailable", "eventCount": None})


if __name__ == "__main__":
    unittest.main()

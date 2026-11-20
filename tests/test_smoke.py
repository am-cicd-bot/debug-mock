import os
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "core-ledger"))


class CoreLedgerSmokeTest(unittest.TestCase):
    def test_health_and_seeded_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CORE_LEDGER_DB"] = os.path.join(tmp, "ledger.db")
            from app.main import app as ledger_app  # type: ignore

            with TestClient(ledger_app) as client:
                r = client.get("/healthz")
                self.assertEqual(r.status_code, 200)
                accts = client.get("/v1/accounts").json()["accounts"]
                self.assertGreaterEqual(len(accts), 4)


if __name__ == "__main__":
    unittest.main()

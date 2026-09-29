import json
import tempfile
import unittest
from pathlib import Path

from ytmusicvault.core.accounts import AccountStore
from ytmusicvault.core.auth import AuthManager, normalize_headers


def credentials(name):
    return normalize_headers({"cookie": f"__Secure-3PAPISID={name}"})


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_legacy_session_and_second_account_are_isolated(self):
        AuthManager(self.root).save(credentials("first"))
        store = AccountStore(self.root)
        self.assertEqual(store.items(), [("default", "原账号")])
        other_id = store.new_id()
        store.auth_for(other_id).save(credentials("second"))
        self.assertTrue(store.register(other_id, "备用账号"))
        self.assertEqual(store.active_id, other_id)
        store.activate("default")
        reloaded = AccountStore(self.root)
        self.assertEqual(reloaded.active_id, "default")
        self.assertEqual(dict(reloaded.items())[other_id], "备用账号")
        self.assertIn("first", reloaded.auth_for("default").load().headers["cookie"])
        self.assertIn("second", reloaded.auth_for(other_id).load().headers["cookie"])
        reloaded.auth_for(other_id).clear()
        reloaded.forget(other_id)
        self.assertTrue(AuthManager(self.root).has_saved_session)
        self.assertEqual(AccountStore(self.root).items(), [("default", "原账号")])

    def test_unsaved_profile_is_not_registered_and_ids_are_confined(self):
        store = AccountStore(self.root)
        self.assertFalse(store.register(store.new_id(), "not saved"))
        self.assertEqual(store.items(), [])
        with self.assertRaises(ValueError):
            store.auth_for("../session.json")
        self.assertFalse(store.path.exists())

    def test_corrupt_index_never_destroys_existing_session(self):
        AuthManager(self.root).save(credentials("original"))
        store = AccountStore(self.root)
        store.path.write_text(json.dumps({"version": 1, "active": "../../x",
                                          "accounts": {"../../x": "escape"}}), encoding="utf-8")
        self.assertEqual(AccountStore(self.root).items(), [("default", "原账号")])
        self.assertIn("original", AuthManager(self.root).load().headers["cookie"])

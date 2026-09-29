import json
import tempfile
import time
import unittest
from pathlib import Path
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from unittest.mock import patch
from ytmusicvault.core.auth import (AuthError, AuthManager, LoginRequest, parse_headers,
    normalize_headers, from_cookie_jar, detect_browsers)


def headers(secret="test-session"):
    return {"Cookie": f"__Secure-3PAPISID={secret}; SID=synthetic-session",
            "X-Goog-AuthUser": "1"}


def cookie(domain, name, value, expires=None):
    return Cookie(0, name, value, None, False, domain, True, domain.startswith("."),
                  "/", True, True, expires, expires is None, None, None, {}, False)


class AuthTests(unittest.TestCase):
    def test_empty_headers_never_open_interactive_stdin(self):
        with patch("builtins.input", side_effect=AssertionError("No stdin allowed")) as read:
            for value in ("", "   ", "\n"):
                with self.assertRaises(AuthError):
                    parse_headers(value)
        read.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = AuthManager(self.tmp.name)

    def test_headers_json_and_text_preserve_account_and_brand(self):
        raw = headers()
        raw["X-Goog-PageId"] = "brand-channel"
        raw["Authorization"] = "SAPISIDHASH stale"
        raw["Host"] = "unrelated.invalid"
        a = parse_headers(json.dumps(raw))
        b = parse_headers("\n".join(f"{k}: {v}" for k, v in raw.items()))
        for credentials in (a, b):
            self.assertEqual(credentials.headers["x-goog-authuser"], "1")
            self.assertEqual(credentials.headers["x-goog-pageid"], "brand-channel")
            self.assertNotIn("host", credentials.headers)
            self.assertNotEqual(credentials.headers["authorization"], "SAPISIDHASH stale")

    def test_invalid_credentials_never_replace_saved_session(self):
        self.manager.save(normalize_headers(headers()))
        before = self.manager.path.read_bytes()
        with self.assertRaises(AuthError):
            self.manager.prepare(LoginRequest("headers", '{"cookie":"SID=bad"}', remember=True))
        self.assertEqual(before, self.manager.path.read_bytes())

    def test_cookie_filter_drops_unrelated_expired_and_prefers_music(self):
        jar = CookieJar()
        for c in (cookie(".youtube.com", "__Secure-3PAPISID", "parent"),
                  cookie("music.youtube.com", "__Secure-3PAPISID", "specific"),
                  cookie(".google.com", "SECRET", "not-for-youtube"),
                  cookie(".youtube.com", "OLD", "expired", int(time.time()) - 10),
                  cookie("youtube.com.evil.test", "EVIL", "wrong")):
            jar.set_cookie(c)
        credentials = from_cookie_jar(jar, "firefox")
        self.assertEqual(credentials.headers["cookie"], "__Secure-3PAPISID=specific")

    def test_netscape_import_and_download_jar_round_trip(self):
        source = Path(self.tmp.name) / "input.txt"
        future = int(time.time()) + 3600
        source.write_text("# Netscape HTTP Cookie File\n"
                          f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t{future}\t__Secure-3PAPISID\ttest-session\n"
                          f".youtube.com\tTRUE\t/\tTRUE\t{future}\tSID\toriginal-sid\n"
                          f".google.com\tTRUE\t/\tTRUE\t{future}\tSECRET\tnot-for-download\n",
                          encoding="utf-8")
        credentials = self.manager.prepare(LoginRequest("file", str(source), account_index="2"))
        self.assertEqual(credentials.headers["x-goog-authuser"], "2")
        output = Path(self.tmp.name) / "output.txt"
        output.write_text(credentials.download_cookies(), encoding="utf-8")
        jar = MozillaCookieJar()
        jar.load(str(output), ignore_discard=True, ignore_expires=True)
        self.assertEqual({c.name for c in jar}, {"__Secure-3PAPISID", "SID"})
        self.assertEqual({c.expires for c in jar}, {future})
        self.assertEqual({c.domain for c in jar}, {".youtube.com"})
        self.manager.save(credentials)
        self.assertEqual(self.manager.load().download_cookies(), credentials.download_cookies())

    def test_embedded_browser_export_uses_same_cookie_import(self):
        raw = ("# Netscape HTTP Cookie File\n"
               ".youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PAPISID\tsynthetic\n")
        credentials = self.manager.prepare(LoginRequest("embedded", raw, account_index="3"))
        self.assertEqual(credentials.source, "embedded")
        self.assertEqual(credentials.headers["x-goog-authuser"], "3")
        self.assertIn("__Secure-3PAPISID", credentials.download_cookies())

    def test_expired_only_and_malformed_files_rejected(self):
        file = Path(self.tmp.name) / "bad.txt"
        for contents in ("not a cookie file",
                         "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1\t__Secure-3PAPISID\texpired\n"):
            file.write_text(contents, encoding="utf-8")
            with self.assertRaises(AuthError):
                self.manager.prepare(LoginRequest("file", str(file)))

    def test_atomic_save_reload_legacy_migration_logout(self):
        legacy = Path(self.tmp.name) / "headers.json"
        legacy.write_text(json.dumps(headers()), encoding="utf-8")
        self.assertTrue(self.manager.has_saved_session)
        credentials = self.manager.load()
        self.assertFalse(self.manager.path.exists())
        self.manager.save(credentials)
        self.assertEqual(self.manager.load().headers["cookie"], credentials.headers["cookie"])
        self.manager.clear()
        self.assertFalse(self.manager.has_saved_session)

    def test_bad_saved_file_is_retained(self):
        self.manager.path.write_text("broken", encoding="utf-8")
        with self.assertRaises(AuthError):
            self.manager.load()
        self.assertEqual(self.manager.path.read_text(), "broken")

    def test_failed_atomic_replace_preserves_previous_credentials(self):
        self.manager.save(normalize_headers(headers("first")))
        with patch("ytmusicvault.core.auth.os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.manager.save(normalize_headers(headers("second")))
        self.assertIn("first", self.manager.load().headers["cookie"])
        self.assertEqual(list(Path(self.tmp.name).glob(".session-*")), [])

    def test_cookie_extraction_error_does_not_expose_secrets(self):
        with patch("yt_dlp.cookies.extract_cookies_from_browser", side_effect=ValueError("secret-cookie")):
            with self.assertRaises(AuthError) as error:
                self.manager.prepare(LoginRequest("browser", "chrome"))
        self.assertNotIn("secret-cookie", str(error.exception))
        self.assertIn("请求头", str(error.exception))

    def test_control_characters_and_missing_account_rejected(self):
        for data in ({"cookie": "SID=x"}, {"cookie": "__Secure-3PAPISID=x\r\nCookie: leak"},
                     {"cookie": "__Secure-3PAPISID=x", "x-goog-authuser": "-1"}, []):
            with self.assertRaises(AuthError):
                normalize_headers(data)

    def test_no_environment_does_not_probe_relative_paths(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(detect_browsers(), [])


if __name__ == "__main__":
    unittest.main()

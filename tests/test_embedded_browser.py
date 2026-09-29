import unittest
from PySide6.QtNetwork import QNetworkCookie
from ytmusicvault.ui.embedded_browser import youtube_cookie_line


class EmbeddedBrowserTests(unittest.TestCase):
    def test_youtube_cookie_export_and_unrelated_domain_filter(self):
        cookie = QNetworkCookie(b"__Secure-3PAPISID", b"synthetic")
        cookie.setDomain(".youtube.com")
        cookie.setPath("/")
        cookie.setSecure(True)
        cookie.setHttpOnly(True)
        self.assertEqual(youtube_cookie_line(cookie),
                         "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PAPISID\tsynthetic")
        cookie.setDomain(".google.com")
        self.assertIsNone(youtube_cookie_line(cookie))

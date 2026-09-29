import threading
import unittest
from unittest.mock import Mock, patch
import requests
from ytmusicapi import YTMusic
from ytmusicvault.core.auth import normalize_headers
from ytmusicvault.core.ytm_client import (YtmClient, HttpSession, Cancelled, SessionExpired,
    ServiceError, parse_playlist_id, user_error)


class LibraryTests(unittest.TestCase):
    def test_first_version_library_endpoint_uses_actual_ytmusicapi(self):
        # Keep real library pagination; replace only the upstream response/parser boundary.
        api = YTMusic.__new__(YTMusic)
        api._check_auth = Mock()
        initial = {"items": [{"createButton": True}, {"playlistId": "PL1", "title": "One"}],
                   "continuations": [{"nextContinuationData": {"continuation": "page2"}}]}
        page2 = {"continuationContents": {"gridContinuation": {
            "items": [{"playlistId": "PL2", "title": "Two"}],
            "continuations": [{"nextContinuationData": {"continuation": "page3"}}]}}}
        page3 = {"continuationContents": {"gridContinuation": {
            "items": [{"playlistId": "PL3", "title": "Three"}]}}}
        api._send_request = Mock(side_effect=[{}, page2, page3])
        with patch("ytmusicapi.mixins.library.get_library_contents", return_value=initial), patch(
                "ytmusicapi.mixins.library.parse_content_list", side_effect=lambda items, parser: items):
            playlists = YtmClient(api).get_playlists()
        self.assertEqual([p.playlist_id for p in playlists], ["PL1", "PL2", "PL3"])
        self.assertEqual(api._send_request.call_count, 3)

    def test_nullable_counts_duplicates_and_owned(self):
        api = Mock()
        api.get_library_playlists.return_value = [
            {"playlistId": "PL1", "title": "收藏", "count": None},
            {"playlistId": "PL1"}, {"title": "no ID"},
            {"playlistId": "PL2", "count": "1,234", "owned": True}, {"playlistId": "LM"}]
        result = YtmClient(api).get_playlists()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].count, 0)
        self.assertEqual(result[1].count, 1234)
        self.assertTrue(result[1].owned)

    def test_playlist_signature_unavailable_tracks_and_duplicate_positions(self):
        class API:
            # The first-version liked-songs endpoint is used for LM.
            def get_liked_songs(self, limit=5000):
                assert limit == 5000
                song = {"videoId": "id", "title": {"runs": [{"text": "合"}, {"text": "唱"}]},
                        "artists": [{"name": "A"}, {"name": "B"}], "album": None,
                        "duration": None, "duration_seconds": 225, "thumbnails": None}
                return {"tracks": [song, song.copy(), {"title": "deleted"},
                                    {"videoId": "private", "isAvailable": False}]}
            def get_playlist(self, playlistId, limit=100):
                assert playlistId != "LM" and limit == 5000
                return {"tracks": []}
        result = YtmClient(API()).get_tracks("LM")
        self.assertEqual(len(result.songs), 2)
        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.songs[0].duration_str, "3:45")
        self.assertEqual(result.songs[0].title, "合唱")
        self.assertEqual(result.songs[0].artist, "A, B")

    def test_empty_playlist_is_valid_missing_tracks_is_failure(self):
        api = Mock()
        api.get_playlist.return_value = {"tracks": []}
        self.assertEqual(YtmClient(api).get_tracks("PLempty").songs, [])
        api.get_playlist.return_value = {}
        with self.assertRaises(ServiceError):
            YtmClient(api).get_tracks("PLmissing")

    def test_first_version_playlist_and_liked_endpoints(self):
        api = Mock()
        api.get_liked_songs.return_value = {"tracks": []}
        api.get_playlist.return_value = {"tracks": []}
        api.get_library_playlists.return_value = []
        client = YtmClient(api)
        client.get_tracks("LM")
        client.get_tracks("PL1")
        api.get_liked_songs.assert_called_once_with(limit=5000)
        api.get_playlist.assert_called_once_with("PL1", limit=5000)
        client.get_playlists()
        api.get_library_playlists.assert_called_once_with(limit=100)

    def test_playlist_link_validation(self):
        self.assertEqual(parse_playlist_id("https://music.youtube.com/playlist?list=PLabc&x=y"), "PLabc")
        for value in ("https://evil.test/?list=PLx", "https://youtube.com/watch?v=x", "../x"):
            with self.assertRaises(ServiceError):
                parse_playlist_id(value)

    def test_connect_fetches_account_display_name_without_gating_login(self):
        api = Mock()
        api.get_account_info.return_value = {"accountName": "Google Display Name", "channelHandle": "@sample"}
        with patch("ytmusicvault.core.ytm_client.YTMusic", return_value=api):
            client, account = YtmClient.connect(normalize_headers({"cookie": "__Secure-3PAPISID=fake"}))
            self.assertFalse(account["verified"], "identity lookup must not change the original persistence gate")
            self.assertTrue(account["identityAvailable"])
            self.assertEqual(account["accountName"], "Google Display Name")
            api.get_account_info.assert_called_once()
            client.close()

    def test_account_identity_failure_is_best_effort(self):
        api = Mock()
        api.get_account_info.side_effect = RuntimeError("account menu unavailable")
        with patch("ytmusicvault.core.ytm_client.YTMusic", return_value=api):
            client, account = YtmClient.connect(normalize_headers({"cookie": "__Secure-3PAPISID=fake"}))
        self.assertIsNotNone(client)
        self.assertEqual(account, {"accountName": "账号未验证", "verified": False, "identityAvailable": False})
        client.close()

    def test_ytmusic_requests_receive_explicit_system_proxy_map(self):
        api = Mock()
        api.get_account_info.return_value = {}
        system_proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        with patch("ytmusicvault.utils.proxy.getproxies", return_value=system_proxies), \
                patch("ytmusicvault.core.ytm_client.YTMusic", return_value=api) as factory:
            client, _ = YtmClient.connect(normalize_headers({"cookie": "__Secure-3PAPISID=fake"}))
        session = factory.call_args.kwargs["requests_session"]
        self.assertEqual(session.proxies, system_proxies)
        self.assertEqual(factory.call_args.kwargs["proxies"], system_proxies)
        self.assertTrue(session.trust_env)
        client.close()

    def test_network_timeouts_auth_failure_and_cancellation(self):
        session = HttpSession()
        self.addCleanup(session.close)
        response = requests.Response()
        response.status_code = 200
        with patch.object(requests.Session, "request", return_value=response) as request:
            session.get("https://music.youtube.com/")
            self.assertEqual(request.call_args.kwargs["timeout"], (10, 30))
            response.status_code = 401
            with self.assertRaises(SessionExpired):
                session.get("https://music.youtube.com/")
            session.cancel_event.set()
            request.reset_mock()
            with self.assertRaises(Cancelled):
                session.get("https://music.youtube.com/")
            request.assert_not_called()

    def test_errors_do_not_leak_headers(self):
        self.assertNotIn("secret", user_error(ValueError("cookie=secret")))
        self.assertIn("代理", user_error(requests.exceptions.ProxyError("secret")))


if __name__ == "__main__":
    unittest.main()

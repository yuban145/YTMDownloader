"""Read-only account-index probe. Prints counts only, never Cookie values."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ytmusicapi import YTMusic
from ytmusicvault.core.auth import AuthManager, LoginRequest
from ytmusicvault.core.ytm_client import user_error


def main():
    if len(sys.argv) != 2:
        return 2
    proxy = "http://127.0.0.1:7890"
    for index in range(4):
        try:
            credentials = AuthManager().prepare(LoginRequest(
                "file", sys.argv[1], account_index=str(index)))
            api = YTMusic(auth=dict(credentials.headers),
                          proxies={"http": proxy, "https": proxy})
            playlists = api.get_library_playlists(limit=100)
            print(f"index={index}; playlists={len(playlists)}", flush=True)
            try:
                liked = api.get_liked_songs(limit=1)
                print(f"index={index}; liked={len(liked.get('tracks') or [])}", flush=True)
            except Exception as exc:
                print(f"index={index}; liked_error={user_error(exc)}", flush=True)
            try:
                lm = api.get_playlist("LM", limit=1)
                print(f"index={index}; lm_tracks={len(lm.get('tracks') or [])}", flush=True)
            except Exception as exc:
                print(f"index={index}; lm_error={user_error(exc)}", flush=True)
        except Exception as exc:
            print(f"index={index}; error={user_error(exc)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

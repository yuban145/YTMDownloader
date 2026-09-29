"""Download-only official song/video counterpart lookup.

The library login and playlist-loading client are deliberately not involved.
"""
from ytmusicapi import YTMusic

from .ytm_client import HttpSession, Cancelled, ServiceError
from ..utils.proxy import configure_requests_session


def find_counterpart(api, song):
    response = api.get_watch_playlist(videoId=song.video_id, limit=1)
    if not isinstance(response, dict):
        raise ServiceError("无法确认此曲对应的 MV，请稍后重试。")
    for track in response.get("tracks") or []:
        if not isinstance(track, dict) or track.get("videoId") != song.video_id:
            continue
        if track.get("videoType") in {"MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC"}:
            return song.video_id
        counterpart = track.get("counterpart") or {}
        if isinstance(counterpart, dict) and counterpart.get("videoId") and counterpart.get("videoType") != "MUSIC_VIDEO_TYPE_ATV":
            return counterpart["videoId"]
    raise ServiceError("此曲未返回对应 MV；可切换音频模式，或打开包含 MV 的歌单。")


def resolve_mv(song, credentials, proxy_url, cancel_event):
    if cancel_event.is_set():
        raise Cancelled()
    # One short-lived session per download worker. The existing library client
    # is never touched, so download errors cannot invalidate its login state.
    session = HttpSession(cancel_event)
    proxies = configure_requests_session(session, proxy_url)
    try:
        api = YTMusic(auth=dict(credentials.headers), requests_session=session,
                      proxies=proxies or None, language="en", user=credentials.headers.get("x-goog-pageid"))
        video_id = find_counterpart(api, song)
        if cancel_event.is_set():
            raise Cancelled()
        return video_id
    finally:
        session.close()

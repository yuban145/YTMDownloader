"""Credential-free network status matching urllib/yt-dlp system discovery."""
from urllib.request import getproxies
from urllib.parse import urlsplit


def requests_proxy_map(proxy_url):
    """Return explicit proxies for requests, including Windows system settings.

    requests only reads environment proxy variables by default. urllib's
    getproxies() also discovers the Windows Internet Settings proxy, so copy
    those values into the Session rather than relying on requests to find them.
    """
    if proxy_url is None:
        discovered = getproxies()
        result = {key: discovered[key] for key in ("http", "https") if discovered.get(key)}
        fallback = discovered.get("all")
        if fallback:
            result.setdefault("http", fallback)
            result.setdefault("https", fallback)
        return result
    if not proxy_url:
        return {}
    return {"http": proxy_url, "https": proxy_url}


def configure_requests_session(session, proxy_url):
    """Apply system/manual/direct proxy policy consistently to a Session."""
    session.trust_env = proxy_url is None
    session.proxies.clear()
    session.proxies.update(requests_proxy_map(proxy_url))
    return session.proxies


def proxy_description(proxy_url):
    if proxy_url is None:
        proxies = getproxies()
        value = proxies.get("https") or proxies.get("all") or proxies.get("http")
        prefix = "系统代理"
        if not value:
            return "跟随系统代理：未检测到静态代理，将直接连接。支持 Windows 系统代理和代理环境变量；不解析 PAC 脚本。"
    elif not proxy_url:
        return "仅下载直连（音乐库连接保持原有方式）"
    else:
        prefix, value = "手动代理", proxy_url
    try:
        parsed = urlsplit(value if "://" in value else "http://" + value)
        return f"{prefix}：{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}（不显示认证信息）"
    except ValueError:
        return f"{prefix}已设置，但地址格式需要检查。"

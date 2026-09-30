"""Credential-free network status matching urllib/yt-dlp system discovery."""
from urllib.request import getproxies
from urllib.parse import urlsplit


def resolve_proxy_url(proxy_url):
    if proxy_url and proxy_url.startswith("pac:"):
        from .pac import pac_proxy_url
        return pac_proxy_url(proxy_url[4:])
    return proxy_url


def requests_proxy_map(proxy_url):
    """Return explicit proxies for requests, including Windows system settings.

    urllib discovers environment variables and Windows static system proxies.
    This map is for inspection; system-mode Sessions resolve it per URL so
    NO_PROXY and Windows bypass rules remain effective.
    """
    proxy_url = resolve_proxy_url(proxy_url)
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
    if proxy_url is not None:
        session.proxies.update(requests_proxy_map(proxy_url))
    return session.proxies


def proxy_description(proxy_url):
    if proxy_url and proxy_url.startswith("pac:"):
        return "PAC 自动代理：按目标地址选择代理或直连（配置地址不显示）"
    if proxy_url is None:
        proxies = getproxies()
        value = proxies.get("https") or proxies.get("all") or proxies.get("http")
        prefix = "系统代理"
        if not value:
            return "跟随系统代理：未检测到静态代理，将直接连接。支持 Windows 静态代理和代理环境变量；使用 PAC 请切换到 PAC 自动代理模式。"
    elif not proxy_url:
        return "直连（新建音乐库会话、下载和封面请求）"
    else:
        prefix, value = "手动代理", proxy_url
    try:
        parsed = urlsplit(value if "://" in value else "http://" + value)
        return f"{prefix}：{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}（不显示认证信息）"
    except ValueError:
        return f"{prefix}已设置，但地址格式需要检查。"


def configure_qt_proxy(proxy_url):
    """Set Qt WebEngine's application proxy before creating its profile."""
    from PySide6.QtNetwork import QNetworkProxy, QNetworkProxyFactory
    from urllib.parse import unquote
    if proxy_url is None:
        proxies = requests_proxy_map(None)
        proxy_url = proxies.get("https") or proxies.get("http")
    proxy_url = resolve_proxy_url(proxy_url)
    QNetworkProxyFactory.setUseSystemConfiguration(False)
    if not proxy_url:
        proxy = QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)
    else:
        parsed = urlsplit(proxy_url)
        kind = (QNetworkProxy.ProxyType.Socks5Proxy if parsed.scheme.startswith("socks5")
                else QNetworkProxy.ProxyType.HttpProxy)
        proxy = QNetworkProxy(kind, parsed.hostname, parsed.port or 80,
                              unquote(parsed.username or ""), unquote(parsed.password or ""))
    QNetworkProxy.setApplicationProxy(proxy)
    return proxy

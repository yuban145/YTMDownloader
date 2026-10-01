"""Loopback PAC gateway shared by requests, yt-dlp and Qt WebEngine.

HTTPS rules receive the origin URL (as with browser PAC privacy rules).
TLS payloads are tunneled unchanged; only PAC scripts are downloaded here.
"""
import atexit
import base64
import select
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
import socks
from pypac.parser import PACFile
from pypac.resolver import ProxyResolver

_MAX_PAC = 1024 * 1024
_HOP_HEADERS = {'connection', 'proxy-connection', 'proxy-authorization',
                'proxy-authenticate',
                'keep-alive', 'transfer-encoding', 'te', 'trailer', 'upgrade'}
_gateways = {}
_gateway_lock = threading.Lock()


class PacPolicy:
    def __init__(self, source):
        self.source = source
        self._lock = threading.Lock()
        self._resolver = None
        self._loaded = 0

    def routes(self, url):
        with self._lock:
            if self._resolver is None or time.monotonic() - self._loaded > 300:
                self._resolver = self._load()
                self._loaded = time.monotonic()
            routes = self._resolver.get_proxies(url)
            # PAC SOCKS routes delegate destination DNS to the proxy.
            return [route.replace("socks5://", "socks5h://", 1) for route in routes]

    def _load(self):
        parsed = urlsplit(self.source)
        if parsed.scheme in ('http', 'https'):
            # Fetch PAC directly, never via itself or an inherited proxy.
            with requests.Session() as session:
                session.trust_env = False
                with session.get(self.source, timeout=(5, 10), stream=True) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > _MAX_PAC:
                            raise ValueError('PAC file exceeds size limit')
        else:
            if parsed.scheme == 'file':
                path = unquote(parsed.path)
                if parsed.netloc not in ('', 'localhost'):
                    raise ValueError('PAC file must be local')
                if len(path) > 2 and path[0] == '/' and path[2] == ':':
                    path = path[1:]
            else:
                path = self.source
            with Path(path).expanduser().open('rb') as stream:
                data = stream.read(_MAX_PAC + 1)
            if len(data) > _MAX_PAC:
                raise ValueError('PAC file exceeds size limit')
        return ProxyResolver(PACFile(bytes(data).decode('utf-8-sig')), socks_scheme='socks5')


def _connect(route, host, port):
    if route == 'DIRECT':
        return socket.create_connection((host, port), timeout=10)
    proxy = urlsplit(route)
    if proxy.scheme in ('socks4', 'socks5', 'socks5h'):
        return socks.create_connection((host, port), timeout=10,
            proxy_type=socks.SOCKS4 if proxy.scheme == 'socks4' else socks.SOCKS5,
            proxy_addr=proxy.hostname, proxy_port=proxy.port or 1080,
            proxy_rdns=proxy.scheme != 'socks5',
            proxy_username=unquote(proxy.username or ''), proxy_password=unquote(proxy.password or ''))
    if proxy.scheme not in ('http', 'https'):
        raise OSError('Unsupported PAC proxy protocol')
    upstream = socket.create_connection((proxy.hostname, proxy.port or (443 if proxy.scheme == 'https' else 80)), timeout=10)
    try:
        if proxy.scheme == 'https':
            upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=proxy.hostname)
        authority = f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
        headers = [f'CONNECT {authority} HTTP/1.1', f'Host: {authority}']
        if proxy.username is not None or proxy.password is not None:
            credentials = f'{unquote(proxy.username or "")}:{unquote(proxy.password or "")}'.encode('utf-8')
            headers.append('Proxy-Authorization: Basic ' + base64.b64encode(credentials).decode('ascii'))
        upstream.sendall(('\r\n'.join(headers) + '\r\n\r\n').encode('ascii'))
        headers = bytearray()
        while not headers.endswith(b'\r\n\r\n'):
            byte = upstream.recv(1)
            if not byte or len(headers) >= 65536:
                raise OSError('Invalid upstream CONNECT response')
            headers.extend(byte)
        if headers.split(b'\r\n', 1)[0].split()[1] != b'200':
            raise OSError('Upstream proxy rejected CONNECT')
        return upstream
    except Exception:
        upstream.close()
        raise


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log URLs, credentials, or cookies.

    def do_CONNECT(self):
        upstream = None
        try:
            target = urlsplit('https://' + self.path)
            if not target.hostname or not target.port:
                raise ValueError('Invalid CONNECT authority')
            for route in self.server.policy.routes('https://' + self.path + '/'):
                try:
                    upstream = _connect(route, target.hostname, target.port)
                    break
                except (OSError, ValueError):
                    continue
            if upstream is None:
                raise OSError('All PAC routes failed')
        except Exception:
            self._routing_error()
            return
        self.send_response(200, 'Connection Established')
        self.end_headers()
        try:
            # Read raw sockets after CONNECT; TLS stays encrypted end to end.
            while True:
                readable, _, _ = select.select([self.connection, upstream], [], [], 60)
                if not readable:
                    break
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()
            self.close_connection = True

    def _routing_error(self):
        try:
            self.send_error(502, "PAC routing failed")
        except OSError:
            pass
        self.close_connection = True

    def _http(self):
        started = False
        try:
            if urlsplit(self.path).scheme != 'http':
                raise ValueError('Absolute HTTP URL required')
            if self.headers.get('Transfer-Encoding'):
                self.send_error(501, 'Chunked request bodies are unsupported')
                return
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 16 * 1024 * 1024:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            hop = _HOP_HEADERS | {x.strip().lower() for x in self.headers.get('Connection', '').split(',')}
            headers = {k: v for k, v in self.headers.items() if k.lower() not in hop}
            with requests.Session() as session:
                session.trust_env = False
                response = None
                for route in self.server.policy.routes(self.path):
                    try:
                        proxies = {} if route == 'DIRECT' else {'http': route, 'https': route}
                        response = session.request(self.command, self.path, headers=headers, data=body,
                            proxies=proxies, timeout=(10, 30), stream=True, allow_redirects=False)
                        break
                    except requests.RequestException:
                        continue
                if response is None:
                    raise OSError('All PAC routes failed')
                with response:
                    started = True
                    self.send_response(response.status_code)
                    response_hop = _HOP_HEADERS | {
                        name.strip().lower()
                        for name in response.headers.get('Connection', '').split(',')
                    }
                    for key, value in response.headers.items():
                        if key.lower() not in response_hop and key.lower() != 'set-cookie':
                            self.send_header(key, value)
                    # Set-Cookie is not a comma-combinable header. Requests'
                    # mapping joins repeated values, so forward urllib3's list.
                    for value in response.raw.headers.getlist('Set-Cookie'):
                        self.send_header('Set-Cookie', value)
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    if self.command != 'HEAD':
                        for chunk in response.raw.stream(65536, decode_content=False):
                            self.wfile.write(chunk)
                    self.close_connection = True
        except Exception:
            if not started:
                self._routing_error()
            self.close_connection = True

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = _http


class PacGateway:
    def __init__(self, source):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.server.daemon_threads = True
        self.server.policy = PacPolicy(source)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def pac_proxy_url(source):
    if not source.strip():
        raise requests.exceptions.ProxyError('PAC address is required')
    with _gateway_lock:
        if source not in _gateways:
            _gateways[source] = PacGateway(source)
        return _gateways[source].url


@atexit.register
def close_gateways():
    for gateway in list(_gateways.values()):
        gateway.close()
    _gateways.clear()

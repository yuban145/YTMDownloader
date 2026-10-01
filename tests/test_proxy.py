"""Real loopback PAC routing, HTTPS tunnels and proxy-policy regressions."""
import os
import ssl
import socket
import socketserver
import select
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests
from PySide6.QtNetwork import QNetworkProxy
from ytmusicvault.utils.config import AppConfig
from ytmusicvault.utils.proxy import configure_requests_session, configure_qt_proxy, resolve_proxy_url
from ytmusicvault.utils.pac import PacGateway, PacPolicy, _Handler, _connect
from ytmusicvault.core.downloader import Downloader


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.hits = []
        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                cls.hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'OK')
        cls.origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        cls.thread = threading.Thread(target=cls.origin.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.origin.server_port}/sample'
        fixtures = Path(__file__).parent / 'fixtures'
        key, cert = fixtures / 'localhost-test-key.pem', fixtures / 'localhost-test-cert.pem'
        cls.cert = cert
        cls.tls = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        cls.tls.socket = context.wrap_socket(cls.tls.socket, server_side=True)
        cls.tls_thread = threading.Thread(target=cls.tls.serve_forever, daemon=True)
        cls.tls_thread.start()
        cls.https_url = f'https://127.0.0.1:{cls.tls.server_port}/encrypted'

    @classmethod
    def tearDownClass(cls):
        for server in (cls.origin, cls.tls):
            server.shutdown(); server.server_close()
        cls.thread.join(); cls.tls_thread.join()
        cls.temp.cleanup()

    def gateway(self, result):
        path = self.root / (self._testMethodName + uuid.uuid4().hex + '.pac')
        path.write_text('function FindProxyForURL(url, host) { return "' + result + '"; }')
        gateway = PacGateway(str(path))
        self.addCleanup(gateway.close)
        return gateway

    def session(self, proxy):
        session = requests.Session()
        configure_requests_session(session, proxy)
        self.addCleanup(session.close)
        return session

    def test_default_port_and_config_modes_roundtrip(self):
        self.assertEqual(AppConfig().proxy_url, 'http://127.0.0.1:7890')
        path = self.root / 'config.json'
        for mode in ('manual', 'system', 'direct', 'pac'):
            config = AppConfig(proxy_mode=mode, proxy_pac_url='http://localhost/rules.pac',
                               _config_path=str(path))
            config.save()
            self.assertEqual(AppConfig.load(str(path)).proxy_url, config.proxy_url)

    def test_pac_matches_each_target_and_local_file_uri(self):
        path = self.root / 'rules.pac'
        path.write_text('function FindProxyForURL(url, host) { '
                        'if (dnsDomainIs(host, ".youtube.com")) return "PROXY 127.0.0.1:7890"; '
                        'return "DIRECT"; }')
        policy = PacPolicy(path.as_uri())
        self.assertEqual(policy.routes('https://music.youtube.com/'), ['http://127.0.0.1:7890'])
        self.assertEqual(policy.routes(self.url), ['DIRECT'])

    def test_pac_direct_ignores_environment_and_tunnels_verified_tls(self):
        gateway = self.gateway('DIRECT')
        session = self.session(gateway.url)
        with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'https_proxy': 'http://127.0.0.1:1'}):
            self.assertEqual(session.get(self.url, timeout=5).text, 'OK')
            self.assertEqual(session.get(self.https_url, timeout=5, verify=str(self.cert)).text, 'OK')

    def test_proxy_route_and_declared_fallback(self):
        visits = []
        class Upstream(_Handler):
            def do_GET(self):
                visits.append(self.path)
                return self._http()
            def do_CONNECT(self):
                visits.append(self.path)
                return super().do_CONNECT()
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        upstream.daemon_threads = True
        upstream.policy = self.gateway('DIRECT').server.policy
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        gateway = self.gateway(f'PROXY 127.0.0.1:1; PROXY 127.0.0.1:{upstream.server_port}')
        session = self.session(gateway.url)
        self.assertEqual(session.get(self.url, timeout=5).text, 'OK')
        self.assertEqual(session.get(self.https_url, timeout=5, verify=str(self.cert)).text, 'OK')
        self.assertIn(self.url, visits)
        self.assertIn(f'127.0.0.1:{self.tls.server_port}', visits)
        direct = self.gateway('PROXY 127.0.0.1:1; DIRECT')
        self.assertEqual(self.session(direct.url).get(self.url, timeout=5).text, 'OK')

    def test_http_response_preserves_repeated_set_cookie_and_strips_connection_headers(self):
        class CookieOrigin(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('Set-Cookie', 'first=one; Path=/')
                self.send_header('Set-Cookie', 'second=two; Path=/')
                self.send_header('Connection', 'X-Origin-Hop')
                self.send_header('X-Origin-Hop', 'must-not-cross-proxy')
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'OK')
        origin = ThreadingHTTPServer(('127.0.0.1', 0), CookieOrigin)
        threading.Thread(target=origin.serve_forever, daemon=True).start()
        self.addCleanup(origin.server_close); self.addCleanup(origin.shutdown)
        gateway = self.gateway('DIRECT')
        with socket.create_connection(('127.0.0.1', gateway.server.server_port), timeout=5) as client:
            client.sendall((f'GET http://127.0.0.1:{origin.server_port}/ HTTP/1.1\r\n'
                            'Host: 127.0.0.1\r\nConnection: close\r\n\r\n').encode('ascii'))
            response = bytearray()
            while True:
                block = client.recv(4096)
                if not block:
                    break
                response.extend(block)
        headers = bytes(response).split(b'\r\n\r\n', 1)[0]
        self.assertEqual(headers.count(b'Set-Cookie:'), 2)
        self.assertIn(b'first=one', headers)
        self.assertIn(b'second=two', headers)
        self.assertNotIn(b'X-Origin-Hop:', headers)
        self.assertNotIn(b'Connection: X-Origin-Hop', headers)

    def test_http_connect_upstream_sends_decoded_proxy_credentials(self):
        received = []
        class Proxy(socketserver.StreamRequestHandler):
            def handle(self):
                request = bytearray()
                while not request.endswith(b'\r\n\r\n'):
                    request.extend(self.rfile.read(1))
                received.append(bytes(request))
                self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        proxy = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Proxy)
        proxy.daemon_threads = True
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        self.addCleanup(proxy.server_close); self.addCleanup(proxy.shutdown)
        tunnel = _connect(f'http://user%40name:p%3Ass@127.0.0.1:{proxy.server_address[1]}',
                          'example.test', 443)
        tunnel.close()
        self.assertEqual(len(received), 1)
        self.assertIn(b'Proxy-Authorization: Basic ' + b'dXNlckBuYW1lOnA6c3M=', received[0])

    def test_bad_pac_and_failed_proxy_never_silently_connect_directly(self):
        self.hits.clear()
        gateway = self.gateway('PROXY 127.0.0.1:1')
        self.assertEqual(self.session(gateway.url).get(self.url, timeout=5).status_code, 502)
        Path(gateway.server.policy.source).write_text('broken script')
        gateway.server.policy._loaded = 0
        self.assertEqual(self.session(gateway.url).get(self.url, timeout=5).status_code, 502)
        self.assertEqual(self.hits, [])

    def test_socks_pac_routes_http_and_tls_with_proxy_dns(self):
        hosts = []
        class SocksHandler(socketserver.StreamRequestHandler):
            def handle(self):
                version, count = self.rfile.read(2)
                self.rfile.read(count)
                self.wfile.write(b"\x05\x00")
                version, command, reserved, kind = self.rfile.read(4)
                if kind == 3:
                    size = self.rfile.read(1)[0]
                    host = self.rfile.read(size).decode()
                else:
                    host = socket.inet_ntoa(self.rfile.read(4))
                hosts.append(host)
                port = int.from_bytes(self.rfile.read(2), 'big')
                with socket.create_connection(('127.0.0.1', port), timeout=5) as upstream:
                    self.wfile.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                    while True:
                        readable, _, _ = select.select([self.connection, upstream], [], [], 5)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (upstream if source is self.connection else self.connection).sendall(data)
        server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), SocksHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        gateway = self.gateway(f'SOCKS 127.0.0.1:{server.server_address[1]}')
        session = self.session(gateway.url)
        url = self.url.replace('127.0.0.1', 'proxy-dns.invalid')
        self.assertEqual(session.get(url, timeout=5).text, 'OK')
        self.assertIn('proxy-dns.invalid', hosts)
        self.assertEqual(session.get(self.https_url, timeout=5, verify=str(self.cert)).text, 'OK')

    def test_remote_pac_download_and_refresh(self):
        class PacOrigin(BaseHTTPRequestHandler):
            script = b'function FindProxyForURL(url, host) { return "DIRECT"; }'
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(self.script)
        server = ThreadingHTTPServer(('127.0.0.1', 0), PacOrigin)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        policy = PacPolicy(f'http://127.0.0.1:{server.server_port}/rules.pac')
        self.assertEqual(policy.routes(self.url), ['DIRECT'])
        PacOrigin.script = b'function FindProxyForURL(url, host) { return "PROXY 127.0.0.1:7890"; }'
        policy._loaded = 0
        self.assertEqual(policy.routes(self.url), ['http://127.0.0.1:7890'])

    def test_system_no_proxy_and_manual_direct_ignore_environment(self):
        env = {'http_proxy': 'http://127.0.0.1:1', 'no_proxy': '127.0.0.1'}
        with patch.dict(os.environ, env):
            self.assertEqual(self.session(None).get(self.url, timeout=5).text, 'OK')
            self.assertEqual(self.session('').get(self.url, timeout=5).text, 'OK')
            proxy = self.gateway('DIRECT').url
            self.assertEqual(self.session(proxy).get(self.url, timeout=5).text, 'OK')

    def test_pac_uses_same_gateway_for_qt_requests_and_downloader(self):
        path = self.root / 'shared.pac'
        path.write_text('function FindProxyForURL(url, host) { return "DIRECT"; }')
        marker = 'pac:' + str(path)
        url = resolve_proxy_url(marker)
        session = self.session(marker)
        self.assertEqual(session.proxies['https'], url)
        cmd = Downloader('unused', proxy_url=marker)._build_command(self.url, 'out')
        self.assertEqual(cmd[cmd.index('--proxy') + 1], url)
        original = QNetworkProxy.applicationProxy()
        self.addCleanup(QNetworkProxy.setApplicationProxy, original)
        proxy = configure_qt_proxy(marker)
        self.assertEqual(proxy.port(), int(url.rsplit(':', 1)[1]))

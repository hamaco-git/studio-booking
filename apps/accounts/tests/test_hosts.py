from unittest import mock

from django.test import SimpleTestCase, override_settings

from config.netutil import https_origins, local_network_hosts


class HttpsOriginsTests(SimpleTestCase):
    def test_domains_become_https_origins(self):
        self.assertEqual(
            https_origins(["studio.example.ac.kr", ".example.ac.kr"]),
            ["https://studio.example.ac.kr", "https://*.example.ac.kr"],
        )

    def test_ips_localhost_and_local_names_are_skipped(self):
        hosts = ["localhost", "127.0.0.1", "192.168.50.100", "[::1]", "*", "mac.local"]
        self.assertEqual(https_origins(hosts), [])


class LocalNetworkHostsTests(SimpleTestCase):
    def test_includes_hostname_and_dot_local(self):
        with mock.patch("config.netutil._private_ipv4s", return_value=["192.168.0.7"]), \
                mock.patch("config.netutil.socket.gethostname", return_value="Hama-Mac"):
            self.assertEqual(
                local_network_hosts(), ["192.168.0.7", "hama-mac", "hama-mac.local"]
            )


class DisallowedHostTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=["localhost"])
    def test_unknown_host_is_400_and_logged(self):
        with self.assertLogs("django.security.DisallowedHost", "WARNING") as logs:
            response = self.client.get("/", HTTP_HOST="10.1.2.3:8000")
        self.assertEqual(response.status_code, 400)
        self.assertIn("10.1.2.3:8000", logs.output[0])

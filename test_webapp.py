import contextlib
import io
import unittest
from unittest.mock import patch

import webapp
from image_processor import EXTENSIONS


def parse_error(*argv) -> str:
    err = io.StringIO()
    with contextlib.redirect_stderr(err), unittest.TestCase().assertRaises(SystemExit):
        webapp.parse_args(list(argv))
    return err.getvalue()


class TestParseArgs(unittest.TestCase):
    def test_defaults_are_local_only_and_not_debug(self):
        args = webapp.parse_args([])
        self.assertEqual((args.host, args.port, args.debug), ("127.0.0.1", 5000, False))

    def test_host_and_port_can_be_set(self):
        args = webapp.parse_args(["--host", "0.0.0.0", "--port", "8080"])
        self.assertEqual((args.host, args.port), ("0.0.0.0", 8080))

    def test_debug_is_allowed_on_a_local_host(self):
        self.assertTrue(webapp.parse_args(["--debug"]).debug)
        self.assertTrue(webapp.parse_args(["--debug", "--host", "127.0.0.1"]).debug)

    def test_debug_is_refused_when_exposed_to_the_network(self):
        self.assertIn("--debug is only allowed with a local --host", parse_error("--debug", "--host", "0.0.0.0"))
        parse_error("--debug", "--host", "192.168.0.10")


class TestLanIp(unittest.TestCase):
    def test_returns_an_address_or_none(self):
        ip = webapp.lan_ip()
        self.assertTrue(ip is None or ip.count(".") == 3)

    def test_returns_none_when_the_network_is_unavailable(self):
        with patch("webapp.socket.socket") as sock:
            sock.return_value.connect.side_effect = OSError("no route")
            self.assertIsNone(webapp.lan_ip())


class TestAcceptedFormats(unittest.TestCase):
    def test_heic_and_heif_are_accepted(self):
        self.assertIn(".heic", EXTENSIONS)
        self.assertIn(".heif", EXTENSIONS)


if __name__ == "__main__":
    unittest.main()

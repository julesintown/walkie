"""CLI-Regressionen für die Zeit zwischen Instanz-Lock und betriebsbereiter Brücke."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LifecycleTest(unittest.TestCase):
    def test_start_waits_for_bridge_of_starting_instance(self):
        import cli
        with (patch.object(cli, "walkie_running", return_value=True),
              patch.object(cli, "bridge_ready", side_effect=[False, False, True]) as ready,
              patch("paths.launch") as launch, patch("paths.HERE"),
              patch.object(cli, "install_dir"), patch.object(cli.time, "sleep"),
              patch.object(cli, "ok") as ok):
            cli.cmd_start([])
        launch.assert_not_called()
        self.assertEqual(ready.call_count, 3)
        ok.assert_called_once_with("gestartet")

    def test_stop_retries_quit_then_waits_for_lock_release(self):
        import cli
        with (patch.object(cli, "walkie_running", side_effect=[True, True, True, False]),
              patch.object(cli, "bridge_post", side_effect=[False, True]) as post,
              patch.object(cli.time, "sleep"), patch.object(cli, "ok") as ok):
            cli.cmd_stop([])
        self.assertEqual(post.call_count, 2)
        ok.assert_called_once_with("beendet")

    def test_bridge_publication_failure_releases_server_for_retry(self):
        from bridge import Bridge
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(tmp)
            with patch("bridge.os.replace", side_effect=PermissionError), self.assertRaises(PermissionError):
                bridge.start()
            self.assertIsNone(bridge.httpd)
            self.assertFalse((Path(tmp) / "server.json.tmp").exists())
            try:
                bridge.start()
                self.assertTrue((Path(tmp) / "server.json").exists())
            finally:
                bridge.stop()

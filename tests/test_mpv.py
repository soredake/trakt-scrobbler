import unittest
from queue import Queue
from unittest.mock import patch

from trakt_scrobbler.player_monitors.mpv import MPVMon


class StopLoop(BaseException):
    """Escapes the monitor's `while True` loop in tests."""


class TestMPVRetry(unittest.TestCase):
    """The MPV monitor must survive unexpected errors and keep retrying."""

    def setUp(self):
        # Skip Monitor.__new__, which autoloads the player config from disk.
        # run() only needs the attributes set below.
        self.mon = object.__new__(MPVMon)
        self.mon.ipc_path = "test-ipc"
        self.mon.poll_interval = 0.01
        self.mon.restart_delay = 0.02
        self.mon.vars = {}
        self.mon.poll_timer = None
        self.mon.connected = False
        self.mon.status = {}
        self.mon.scrobble_queue = Queue()
        self.status_updates = []
        self.cc_calls = []

    def run_monitor(self, can_connect, conn_loop, max_cc_calls):
        """Drive run() until can_connect has been called max_cc_calls times."""

        def can_connect_stop():
            self.cc_calls.append(1)
            if len(self.cc_calls) >= max_cc_calls:
                raise StopLoop
            return can_connect()

        self.mon.can_connect = can_connect_stop
        self.mon.conn_loop = conn_loop
        self.mon.update_vars = lambda: None
        self.mon.update_status = (
            lambda: self.status_updates.append(dict(self.mon.vars))
        )
        with patch("time.sleep") as sleep_mock:
            with self.assertRaises(StopLoop):
                self.mon.run()
        return [call.args[0] for call in sleep_mock.call_args_list]

    def test_conn_loop_error_retries(self):
        """An unexpected IPC error is followed by another connection attempt."""
        conn_calls = []

        def can_connect():
            return len(conn_calls) < 2

        def conn_loop():
            conn_calls.append(1)
            if len(conn_calls) == 1:
                raise RuntimeError("unexpected IPC failure")

        sleeps = self.run_monitor(can_connect, conn_loop, max_cc_calls=3)
        self.assertEqual(len(conn_calls), 2, "conn_loop must be retried")
        self.assertEqual(sleeps, [0.01, 0.02])
        self.assertEqual(self.mon.vars, {})

    def test_can_connect_error_retries(self):
        """An error while probing the connection doesn't kill the monitor."""
        probe_calls = []
        conn_calls = []

        def can_connect():
            probe_calls.append(1)
            if len(probe_calls) == 1:
                raise RuntimeError("unexpected probe failure")
            return len(conn_calls) < 2

        def conn_loop():
            conn_calls.append(1)

        sleeps = self.run_monitor(can_connect, conn_loop, max_cc_calls=3)
        self.assertEqual(len(probe_calls), 2, "probe must be retried after error")
        self.assertEqual(len(conn_calls), 1, "monitor must connect after retry")
        self.assertEqual(sleeps, [0.01, 0.02])
        self.assertEqual(self.mon.vars, {})

    def test_normal_session_synthesizes_stop(self):
        """A clean disconnect emits a stop event and clears the state."""
        conn_calls = []

        def can_connect():
            return len(conn_calls) < 2

        def conn_loop():
            conn_calls.append(1)
            self.mon.vars = {
                "state": 2, "path": "video.mkv", "duration": 120,
                "time-pos": 30, "working-directory": "."
            }

        sleeps = self.run_monitor(can_connect, conn_loop, max_cc_calls=2)
        self.assertEqual(len(self.status_updates), 1)
        self.assertEqual(self.status_updates[0]["state"], 0)
        self.assertEqual(self.mon.vars, {})
        self.assertEqual(sleeps, [0.02])

    def test_lost_connection_logged_once(self):
        """A lost connection is reported at INFO once, then stays quiet."""
        self.mon.connected = True

        def can_connect():
            return False

        def conn_loop():
            raise AssertionError("conn_loop must not run")

        with self.assertLogs("trakt_scrobbler", level="INFO") as logs:
            sleeps = self.run_monitor(can_connect, conn_loop, max_cc_calls=3)
        infos = [r.getMessage() for r in logs.records if r.levelname == "INFO"]
        self.assertEqual(len(infos), 1, "INFO must be logged only once")
        self.assertIn("Lost connection to MPV", infos[0])


if __name__ == "__main__":
    unittest.main()

import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import log_setup


class GetLogDirTests(unittest.TestCase):
    def test_darwin_returns_library_logs_mouser(self):
        with patch.object(sys, "platform", "darwin"):
            result = log_setup._get_log_dir()
        self.assertTrue(result.endswith(os.path.join("Library", "Logs", "Mouser")))

    def test_linux_uses_xdg_state_home(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {"XDG_STATE_HOME": "/custom/state"}, clear=False),
        ):
            result = log_setup._get_log_dir()
        self.assertEqual(result, os.path.join("/custom/state", "Mouser", "logs"))

    def test_linux_defaults_to_dot_local_state(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, env, clear=True),
        ):
            result = log_setup._get_log_dir()
        expected = os.path.join(
            os.path.expanduser("~"), ".local", "state", "Mouser", "logs"
        )
        self.assertEqual(result, expected)

    def test_windows_uses_appdata(self):
        fake_appdata = os.path.join("C:", "Users", "test", "AppData", "Roaming")
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(os.environ, {"APPDATA": fake_appdata}, clear=False),
        ):
            result = log_setup._get_log_dir()
        self.assertEqual(result, os.path.join(fake_appdata, "Mouser", "logs"))


class SetupLoggingTests(unittest.TestCase):
    def setUp(self):
        self._orig_stdout = sys.stdout
        self._orig_handlers = logging.root.handlers[:]
        self._orig_level = logging.root.level
        logging.root.handlers.clear()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = self._tmp_dir.name

    def tearDown(self):
        # Restore stdout first so handler.close() can safely write errors to stderr
        sys.stdout = self._orig_stdout
        # Close handlers BEFORE temp dir cleanup to release file locks (Windows)
        for h in logging.root.handlers[:]:
            h.close()
        logging.root.handlers.clear()
        logging.root.handlers.extend(self._orig_handlers)
        logging.root.setLevel(self._orig_level)
        self._tmp_dir.cleanup()

    def test_creates_log_file_on_startup(self):
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            path = log_setup.setup_logging()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(path, os.path.join(self.tmp, "mouser.log"))

    def test_returns_empty_string_when_already_configured(self):
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            log_setup.setup_logging()
            result = log_setup.setup_logging()
        self.assertEqual(result, "")

    def test_redirects_stdout_to_stream_to_logger(self):
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            log_setup.setup_logging()
        self.assertIsInstance(sys.stdout, log_setup._StreamToLogger)

    def test_stderr_not_redirected(self):
        orig_stderr = sys.stderr
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            log_setup.setup_logging()
        self.assertIs(sys.stderr, orig_stderr)

    def test_print_output_written_to_log_file(self):
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            log_setup.setup_logging()
        print("[Test] hello from print")
        for h in logging.root.handlers:
            h.flush()
        log_path = os.path.join(self.tmp, "mouser.log")
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("[Test] hello from print", content)

    def test_log_entries_include_timestamp(self):
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            log_setup.setup_logging()
        print("[Test] timestamped line")
        for h in logging.root.handlers:
            h.flush()
        log_path = os.path.join(self.tmp, "mouser.log")
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        # Timestamp format: "YYYY-MM-DD HH:MM:SS"
        import re
        self.assertRegex(content, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_graceful_fallback_on_oserror(self):
        with patch.object(log_setup, "_get_log_dir", return_value="/nonexistent/xyz"):
            with patch("core.log_setup.os.makedirs", side_effect=OSError("denied")):
                path = log_setup.setup_logging()  # must not raise
        self.assertEqual(path, "")

    def test_no_console_handler_when_frozen(self):
        with (
            patch.object(log_setup, "_get_log_dir", return_value=self.tmp),
            patch.object(sys, "frozen", True, create=True),
        ):
            log_setup.setup_logging()
        handler_types = [type(h) for h in logging.root.handlers]
        self.assertNotIn(logging.StreamHandler, handler_types)

    def test_rotating_handler_configured_with_correct_size(self):
        import logging.handlers
        with patch.object(log_setup, "_get_log_dir", return_value=self.tmp):
            log_setup.setup_logging()
        rotating = next(
            h for h in logging.root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        )
        self.assertEqual(rotating.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(rotating.backupCount, 5)


class StreamToLoggerTests(unittest.TestCase):
    def _make_stream(self, level=logging.INFO):
        logger = logging.getLogger(f"test_stream_{id(self)}")
        logger.handlers.clear()
        logger.propagate = False
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger.addHandler(Capture())
        logger.setLevel(logging.DEBUG)
        return log_setup._StreamToLogger(logger, level), records

    def test_complete_line_is_logged_immediately(self):
        stream, records = self._make_stream()
        stream.write("[Engine] DPI changed\n")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].getMessage(), "[Engine] DPI changed")

    def test_partial_line_is_buffered_until_newline(self):
        stream, records = self._make_stream()
        stream.write("[Engine]")
        self.assertEqual(len(records), 0)
        stream.write(" DPI changed\n")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].getMessage(), "[Engine] DPI changed")

    def test_multiple_lines_in_single_write(self):
        stream, records = self._make_stream()
        stream.write("line one\nline two\nline three\n")
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].getMessage(), "line one")
        self.assertEqual(records[1].getMessage(), "line two")
        self.assertEqual(records[2].getMessage(), "line three")

    def test_flush_emits_partial_buffer(self):
        stream, records = self._make_stream()
        stream.write("no newline")
        self.assertEqual(len(records), 0)
        stream.flush()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].getMessage(), "no newline")

    def test_blank_lines_not_logged(self):
        stream, records = self._make_stream()
        stream.write("\n\n\n")
        self.assertEqual(len(records), 0)

    def test_write_returns_length_of_message(self):
        stream, _ = self._make_stream()
        msg = "hello\n"
        result = stream.write(msg)
        self.assertEqual(result, len(msg))

    def test_isatty_returns_false(self):
        stream, _ = self._make_stream()
        self.assertFalse(stream.isatty())

    def test_encoding_is_utf8(self):
        stream, _ = self._make_stream()
        self.assertEqual(stream.encoding, "utf-8")


if __name__ == "__main__":
    unittest.main()

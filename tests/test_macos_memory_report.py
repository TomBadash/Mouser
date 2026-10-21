import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.macos_memory_report import collect, compare, main, parse_footprint, parse_heap, run_tool


class MacOSMemoryReportTests(unittest.TestCase):
    def test_footprint_units_and_decimal_totals(self):
        for text, expected in (("2082 MB", 2082 * 1024**2),
                               ("3.6 GB", round(3.6 * 1024**3)),
                               ("512 KB", 512 * 1024), ("0 B", 0)):
            with self.subTest(text=text):
                self.assertEqual(parse_footprint(f"Mouser [123]: Footprint: {text}"), expected)

    def test_footprint_does_not_confuse_peak_with_current(self):
        self.assertEqual(parse_footprint("Footprint: 100 MB\nphys_footprint_peak: 4096 MB"),
                         100 * 1024**2)

    def test_heap_exact_names_and_missing_classes(self):
        output = """COUNT BYTES AVG CLASS_NAME TYPE BINARY
 9234053 1034213936 112.0 HIDEvent ObjC IOKit
 3079726 98551232 32.0 CGEvent CFType SkyLight
 3079725 443480400 144.0 CGSEventAppendix CFType CoreGraphics
 10 160 16.0 CGEventSource ObjC Other
"""
        classes = parse_heap(output)
        self.assertEqual(classes["HIDEvent"], {"count": 9234053, "bytes": 1034213936})
        self.assertEqual(classes["CGEvent"]["count"], 3079726)
        self.assertEqual(classes["IOHIDManager"]["count"], 0)

    def test_unrecognized_output_is_not_reported_as_zero(self):
        for parser in (parse_heap, parse_footprint):
            with self.subTest(parser=parser.__name__), self.assertRaises(ValueError):
                parser("Process is not debuggable")

    def test_delta_and_restarted_process(self):
        before = {"pid": 123, "process_identity": "start A Mouser",
                  "footprint_bytes": 100, "classes": parse_heap("COUNT BYTES AVG CLASS_NAME")}
        after = dict(before, footprint_bytes=90,
                     classes=parse_heap("COUNT BYTES AVG CLASS_NAME\n3 336 112.0 HIDEvent ObjC IOKit"))
        self.assertEqual(compare(before, after)["footprint_bytes"], -10)
        self.assertEqual(compare(before, after)["classes"]["HIDEvent"]["count"], 3)
        for changed in (dict(after, pid=456), dict(after, process_identity="start B Mouser")):
            with self.assertRaises(ValueError):
                compare(before, changed)

    def test_process_changes_during_capture(self):
        with patch("tools.macos_memory_report.run_tool", side_effect=[
            "start A Mouser", "Footprint: 100 MB", "COUNT BYTES AVG CLASS_NAME", "start B Mouser"
        ]), self.assertRaisesRegex(ValueError, "changed during collection"):
            collect(123)

    def test_tool_failure_includes_inspection_error(self):
        result = subprocess.CompletedProcess([], 1, "", "inspection denied")
        with patch("tools.macos_memory_report.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ValueError, "inspection denied"):
                run_tool(["/usr/bin/heap", "-s", "123"])

    def test_cli_does_not_overwrite_existing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.json"
            output.write_text("original baseline")
            with patch("tools.macos_memory_report.sys.platform", "darwin"), \
                 patch("tools.macos_memory_report.sys.argv", ["report", "123", "--output", str(output)]), \
                 patch("tools.macos_memory_report.collect", return_value={}), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 1)
            self.assertEqual(output.read_text(), "original baseline")

    def test_cli_inspection_failure_does_not_write_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch("tools.macos_memory_report.sys.platform", "darwin"), \
                 patch("tools.macos_memory_report.sys.argv", ["report", "123", "--output", str(output)]), \
                 patch("tools.macos_memory_report.collect", side_effect=ValueError("inspection denied")), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

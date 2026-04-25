import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import linux_permissions


def _write_logitech_hidraw(sysfs_base, name="hidraw3"):
    device_dir = os.path.join(sysfs_base, name, "device")
    os.makedirs(device_dir)
    with open(os.path.join(device_dir, "uevent"), "w", encoding="utf-8") as fh:
        fh.write("HID_ID=0005:0000046D:0000B034\n")
        fh.write("HID_NAME=Logitech MX Master 3S\n")


class LinuxPermissionTests(unittest.TestCase):
    def test_logitech_hidraw_nodes_reads_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            sysfs_base = os.path.join(tmp, "sys", "class", "hidraw")
            dev_base = os.path.join(tmp, "dev")
            _write_logitech_hidraw(sysfs_base)

            nodes = linux_permissions.logitech_hidraw_nodes(
                sysfs_base=sysfs_base,
                dev_base=dev_base,
            )

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].path, os.path.join(dev_base, "hidraw3"))
        self.assertEqual(nodes[0].product_id, 0xB034)
        self.assertEqual(nodes[0].product_name, "Logitech MX Master 3S")

    def test_report_warns_when_visible_logitech_devices_are_inaccessible(self):
        with tempfile.TemporaryDirectory() as tmp:
            sysfs_base = os.path.join(tmp, "sys", "class", "hidraw")
            dev_base = os.path.join(tmp, "dev")
            input_dir = os.path.join(dev_base, "input")
            os.makedirs(input_dir)
            _write_logitech_hidraw(sysfs_base)

            hidraw_path = os.path.join(dev_base, "hidraw3")
            event_path = os.path.join(input_dir, "event0")
            uinput_path = os.path.join(dev_base, "uinput")
            for path in (hidraw_path, event_path, uinput_path):
                with open(path, "w", encoding="utf-8"):
                    pass

            blocked = {hidraw_path, event_path, uinput_path}

            def fake_access(path, _mode):
                return path not in blocked

            with (
                patch.object(sys, "platform", "linux"),
                patch.object(linux_permissions.os, "access", side_effect=fake_access),
            ):
                report = linux_permissions.linux_permission_report(
                    sysfs_base=sysfs_base,
                    dev_base=dev_base,
                    input_event_glob=os.path.join(input_dir, "event*"),
                    uinput_path=uinput_path,
                )

        self.assertIsNotNone(report)
        self.assertTrue(report.has_issue)
        self.assertEqual(report.blocked_hidraw_paths, (hidraw_path,))
        self.assertFalse(report.input_events_readable)
        self.assertFalse(report.uinput_writable)
        self.assertIn(
            linux_permissions.INSTALL_HELPER,
            linux_permissions.linux_permission_status_message(report),
        )
        self.assertIn(
            "blocked hidraw access",
            linux_permissions.linux_permission_log_message(report),
        )

    def test_report_stays_quiet_when_no_logitech_hidraw_node_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, "platform", "linux"):
                report = linux_permissions.linux_permission_report(
                    sysfs_base=tmp,
                    dev_base=os.path.join(tmp, "dev"),
                    input_event_glob=os.path.join(tmp, "event*"),
                    uinput_path=os.path.join(tmp, "uinput"),
                )

        self.assertIsNotNone(report)
        self.assertFalse(report.has_issue)
        self.assertEqual(linux_permissions.linux_permission_status_message(report), "")

    def test_report_is_disabled_off_linux(self):
        with patch.object(sys, "platform", "darwin"):
            self.assertIsNone(linux_permissions.linux_permission_report())


if __name__ == "__main__":
    unittest.main()

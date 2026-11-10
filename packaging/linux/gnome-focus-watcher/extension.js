// From https://github.com/flexagoon/focused-window-dbus
import Gio from "gi://Gio";
import GLib from "gi://GLib";
import Shell from "gi://Shell";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";

const DBUS_SCHEMA = `
<node>
    <interface name="org.mouser.FocusWatcher">
        <method name="GetFocusApp">
            <arg type="s" direction="out" name="window" />
        </method>
        <signal name="FocusChanged">
            <arg type="s" name="window" />
        </signal>
    </interface>
</node>`;

export default class FocusWatcherExtension extends Extension {
  // 通过 PID 获取可执行文件路径
  #getExecutablePath(pid) {
    if (!pid || pid <= 0) return null;
    try {
      const link = `/proc/${pid}/exe`;
      return GLib.file_read_link(link) || null;
    } catch (e) {
      // 文件不存在或读取失败（如进程已退出）
      return null;
    }
  }

  GetFocusApp() {
    // 直接获取当前焦点窗口，无需遍历
    const focusWindow = global.display.focus_window;
    if (!focusWindow) {
      return "{}";
    }

    const pid = focusWindow.get_pid();
    const exePath = this.#getExecutablePath(pid);

    return JSON.stringify({
      id: focusWindow.get_id(),
      pid: pid,
      title: focusWindow.get_title(),
      wm_class: focusWindow.get_wm_class(),
      wm_class_instance: focusWindow.get_wm_class_instance(),
      executable: exePath || "", // 可执行文件路径，获取不到则为空字符串
    });
  }

  #windowTracker = null;
  #focusConnection = null;
  #dbus = null;

  enable() {
    // 1. 先创建 DBus 导出对象（这样信号回调中才能使用 this.#dbus）
    this.#dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_SCHEMA, this);
    this.#dbus.export(Gio.DBus.session, "/github/mouser");

    // 2. 再连接信号，回调中通过 #dbus 发送信号
    this.#windowTracker = Shell.WindowTracker.get_default();
    this.#focusConnection = this.#windowTracker.connect(
      "notify::focus-app",
      () => {
        const payload = this.GetFocusApp();
        this.#dbus.emit_signal(
          "FocusChanged",
          new GLib.Variant("(s)", [payload]),
        );
      },
    );
  }

  disable() {
    // 断开信号
    if (this.#focusConnection) {
      this.#windowTracker?.disconnect(this.#focusConnection);
      this.#focusConnection = null;
    }
    this.#windowTracker = null;

    // 取消 DBus 导出
    if (this.#dbus) {
      this.#dbus.flush();
      this.#dbus.unexport();
      this.#dbus = null;
    }
  }
}

# coding=utf-8
from __future__ import annotations

import io
import posixpath

import octoprint.plugin
from werkzeug.datastructures import FileStorage

from .gcode_recovery import RecoveryError, generate_recovery_gcode


class MyPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.SimpleApiPlugin,
):
    """Minimal OctoPrint plugin implementation."""

    def on_after_startup(self):
        self._logger.info("MyPlugin loaded and OctoPrint finished starting up.")

    def get_settings_defaults(self):
        return {
            "example_setting": True,
        }

    # --- UI integration ---

    def get_template_configs(self):
        return [
            {
                "type": "sidebar",
                "name": "Continue print where…",
                "template": "myplugin_sidebar.jinja2",
                "custom_bindings": True,
            }
        ]

    def get_assets(self):
        return {
            "js": ["js/myplugin.js"],
            "css": ["css/myplugin.css"],
        }

    # --- API: generate recovery file ---

    def get_api_commands(self):
        return {
            "generate_recovery": ["path", "target_layer"],
        }

    def on_api_command(self, command, data):
        if command != "generate_recovery":
            return

        path = (data or {}).get("path")
        target_layer_raw = (data or {}).get("target_layer")
        safety_z_raw = (data or {}).get("safety_z")

        if not path or not isinstance(path, str):
            raise octoprint.plugin.SimpleApiPlugin.BadRequest("Missing required 'path' (string).")

        try:
            target_layer = int(target_layer_raw)
        except Exception as e:
            raise octoprint.plugin.SimpleApiPlugin.BadRequest(
                "Missing/invalid 'target_layer' (int). Example: 102"
            )

        safety_z = None
        if safety_z_raw not in (None, "", "null"):
            try:
                safety_z = float(safety_z_raw)
            except Exception:
                raise octoprint.plugin.SimpleApiPlugin.BadRequest(
                    "Invalid 'safety_z' (float). Example: 50"
                )

        # Read source file from local storage
        from octoprint.filemanager import FileDestinations

        src_disk_path = self._file_manager.path_on_disk(FileDestinations.LOCAL, path)
        with open(src_disk_path, "rb") as f:
            raw = f.read()

        try:
            source_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            source_text = raw.decode("latin-1", errors="replace")

        try:
            result = generate_recovery_gcode(source_text, target_layer, safety_z=safety_z)
        except RecoveryError as e:
            raise octoprint.plugin.SimpleApiPlugin.BadRequest(str(e))

        # Compute output file name/path
        dir_name = posixpath.dirname(path)
        base_name = posixpath.basename(path)
        stem, ext = posixpath.splitext(base_name)
        if ext.lower() != ".gcode":
            ext = ext or ".gcode"

        out_base = f"{stem}_RECOVERY{ext}"
        out_path = posixpath.join(dir_name, out_base) if dir_name else out_base

        # Ensure uniqueness (avoid clobbering)
        if self._file_manager.file_exists(FileDestinations.LOCAL, out_path):
            n = 1
            while True:
                candidate = f"{stem}_RECOVERY_{n}{ext}"
                candidate_path = posixpath.join(dir_name, candidate) if dir_name else candidate
                if not self._file_manager.file_exists(FileDestinations.LOCAL, candidate_path):
                    out_path = candidate_path
                    break
                n += 1

        out_bytes = result.output_gcode.encode("utf-8")
        storage = FileStorage(
            stream=io.BytesIO(out_bytes),
            filename=posixpath.basename(out_path),
            content_type="text/plain",
        )

        # Add into OctoPrint's local storage
        self._file_manager.add_file(FileDestinations.LOCAL, out_path, storage, allow_overwrite=False)

        return {
            "output_path": out_path,
            "layer_marker_style": result.detected_layer_marker_style,
        }


# Plugin metadata (used by OctoPrint)
__plugin_name__ = "My Plugin"
__plugin_version__ = "0.1.0"
__plugin_pythoncompat__ = ">=3.8,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MyPlugin()



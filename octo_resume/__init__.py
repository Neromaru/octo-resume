# coding=utf-8
from __future__ import annotations

import io
import posixpath

import flask
import octoprint.plugin
from werkzeug.datastructures import FileStorage

from .gcode_recovery import RecoveryError, generate_recovery_gcode


class OctoResumePlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.SimpleApiPlugin,
):
    def on_after_startup(self):
        self._logger.info("Octo Resume loaded.")

    def get_settings_defaults(self):
        return {}

    # --- UI integration ---

    def get_template_configs(self):
        return [
            {
                "type": "sidebar",
                "name": "Octo Resume",
                "template": "octoresume_sidebar.jinja2",
                "custom_bindings": True,
            }
        ]

    def get_assets(self):
        return {
            "js": ["js/octoresume.js"],
            "css": ["css/octoresume.css"],
        }

    # --- Simple API ---

    def is_api_protected(self):
        # Explicitly declare protection status (OctoPrint 1.11.2+ warning otherwise).
        return True

    def get_api_commands(self):
        return {
            "generate_recovery": ["path", "target_layer"],
        }

    def _bad_request(self, msg: str):
        return flask.make_response(flask.jsonify(error=msg), 400)

    def on_api_command(self, command, data):
        if command != "generate_recovery":
            return self._bad_request("Unknown command")

        path = (data or {}).get("path")
        target_layer_raw = (data or {}).get("target_layer")
        safety_z_raw = (data or {}).get("safety_z")

        if not path or not isinstance(path, str):
            return self._bad_request("Missing required 'path' (string).")

        try:
            target_layer = int(target_layer_raw)
        except Exception:
            return self._bad_request("Missing/invalid 'target_layer' (int). Example: 102")

        safety_z = None
        if safety_z_raw not in (None, "", "null"):
            try:
                safety_z = float(safety_z_raw)
            except Exception:
                return self._bad_request("Invalid 'safety_z' (float). Example: 50")

        from octoprint.filemanager import FileDestinations

        # Read source file from local storage
        try:
            src_disk_path = self._file_manager.path_on_disk(FileDestinations.LOCAL, path)
            with open(src_disk_path, "rb") as f:
                raw = f.read()
        except Exception as e:
            self._logger.exception("Failed reading source file for recovery")
            return self._bad_request(f"Failed to read source file '{path}': {e}")

        try:
            source_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            source_text = raw.decode("latin-1", errors="replace")

        try:
            result = generate_recovery_gcode(source_text, target_layer, safety_z=safety_z)
        except RecoveryError as e:
            return self._bad_request(str(e))

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

        try:
            self._file_manager.add_file(
                FileDestinations.LOCAL, out_path, storage, allow_overwrite=False
            )
        except Exception as e:
            self._logger.exception("Failed saving recovery file")
            return self._bad_request(f"Failed to save recovery file '{out_path}': {e}")

        return {
            "output_path": out_path,
            "layer_marker_style": result.detected_layer_marker_style,
        }


__plugin_name__ = "Octo Resume"
__plugin_version__ = "0.1.0"
__plugin_pythoncompat__ = ">=3.8,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = OctoResumePlugin()



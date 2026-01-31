$(function () {
  function MyPluginRecoveryViewModel(parameters) {
    var self = this;

    // Common OctoPrint viewmodel dependency (provided via OCTOPRINT_VIEWMODELS)
    self.filesViewModel = (parameters && parameters.length > 0) ? parameters[0] : null;

    self.recoverySourcePath = ko.observable("");
    self.recoveryTargetLayer = ko.observable("");
    self.recoverySafetyZ = ko.observable("");

    self.isWorking = ko.observable(false);
    self.lastOutputPath = ko.observable("");
    self.selectedFilePath = ko.observable("");

    self.canGenerateRecovery = ko.pureComputed(function () {
      return (
        !self.isWorking() &&
        (self.recoverySourcePath() || "").trim().length > 0 &&
        (self.recoveryTargetLayer() || "").toString().trim().length > 0
      );
    });

    self._extractSelectedLocalPath = function () {
      var fvm = self.filesViewModel;
      if (!fvm || !fvm.selectedFile) return null;
      var f = fvm.selectedFile();
      if (!f) return null;

      // Prefer local origin, because backend writes into LOCAL.
      if (f.origin && f.origin !== "local") return null;

      // Common patterns across OctoPrint versions/plugins: f.path, f.name (+ f.path?), f.display
      if (typeof f.path === "string" && f.path.length > 0) return f.path;
      if (typeof f.name === "string" && f.name.length > 0) return f.name;
      return null;
    };

    self._syncFromSelection = function () {
      var p = self._extractSelectedLocalPath();
      self.selectedFilePath(p || "");
      if (p && (self.recoverySourcePath() || "").trim().length === 0) {
        self.recoverySourcePath(p);
      }
    };

    self.generateRecovery = function () {
      var path = (self.recoverySourcePath() || "").trim();
      var targetLayerRaw = (self.recoveryTargetLayer() || "").toString().trim();
      var safetyZRaw = (self.recoverySafetyZ() || "").toString().trim();

      var targetLayer = parseInt(targetLayerRaw, 10);
      if (isNaN(targetLayer) || targetLayer < 0) {
        new PNotify({
          title: "Recovery",
          text: "Target layer must be a number (>= 0).",
          type: "error",
        });
        return;
      }

      var payload = {
        path: path,
        target_layer: targetLayer,
      };
      if (safetyZRaw.length > 0) {
        payload.safety_z = parseFloat(safetyZRaw);
      }

      self.isWorking(true);
      self.lastOutputPath("");

      OctoPrint.simpleApiCommand("myplugin", "generate_recovery", payload)
        .done(function (resp) {
          self.lastOutputPath(resp.output_path || "");
          try {
            $("#myplugin_recovery_modal").modal("hide");
          } catch (e) {}
          new PNotify({
            title: "Recovery file created",
            text:
              "Created " +
              (resp.output_path || "(unknown)") +
              (resp.layer_marker_style
                ? " (layer markers: " + resp.layer_marker_style + ")"
                : ""),
            type: "success",
          });
        })
        .fail(function (xhr) {
          var msg = "Failed to create recovery file.";
          try {
            if (xhr && xhr.responseJSON && xhr.responseJSON.error) {
              msg = xhr.responseJSON.error;
            }
          } catch (e) {}
          new PNotify({
            title: "Recovery error",
            text: msg,
            type: "error",
          });
        })
        .always(function () {
          self.isWorking(false);
        });
    };

    self.openRecoveryDialogForSelectedFile = function () {
      var p = self._extractSelectedLocalPath();
      if (!p) {
        new PNotify({
          title: "Recovery",
          text: "Select a LOCAL G-code file first (Files list), then try again.",
          type: "error",
        });
        return;
      }

      self.recoverySourcePath(p);
      self._syncFromSelection();

      try {
        $("#myplugin_recovery_modal").modal("show");
        setTimeout(function () {
          $("#myplugin_recovery_target_layer").focus();
        }, 50);
      } catch (e) {
        // If modal isn't available for some reason, still works via sidebar panel.
      }
    };

    self._injectFilesActionButton = function () {
      if ($("#myplugin_recovery_files_action_btn").length) return true;

      // Try a handful of common containers in the Files pane.
      var selectors = [
        "#files .file-actions",
        "#files .files_actions",
        "#files .btn-toolbar",
        "#files .btn-group",
      ];

      var container = null;
      for (var i = 0; i < selectors.length; i++) {
        var el = $(selectors[i]).first();
        if (el && el.length) {
          container = el;
          break;
        }
      }

      if (!container) return false;

      var btn = $(
        '<button id="myplugin_recovery_files_action_btn" class="btn" type="button" title="Generate a recovery G-code from the selected file">Continue print where…</button>'
      );
      btn.on("click", function () {
        self.openRecoveryDialogForSelectedFile();
      });

      container.append(btn);
      return true;
    };

    // Keep sidebar display synced to file selection
    if (self.filesViewModel && self.filesViewModel.selectedFile && self.filesViewModel.selectedFile.subscribe) {
      self.filesViewModel.selectedFile.subscribe(function () {
        self._syncFromSelection();
      });
    }
    self._syncFromSelection();

    // Try to inject the Files action button a few times during startup (DOM loads async).
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (self._injectFilesActionButton() || tries > 20) {
        clearInterval(timer);
      }
    }, 500);
  }

  OCTOPRINT_VIEWMODELS.push({
    construct: MyPluginRecoveryViewModel,
    dependencies: ["filesViewModel"],
    elements: ["#sidebar_plugin_myplugin_recovery", "#myplugin_recovery_modal"],
  });
});



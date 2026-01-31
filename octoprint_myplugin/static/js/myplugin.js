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

    self._extractLocalPathFromFileObject = function (f) {
      if (!f) return null;
      if (f.origin && f.origin !== "local") return null;
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

    self.openRecoveryDialogForPath = function (path) {
      if (!path) return;
      self.recoverySourcePath(path);
      self.selectedFilePath(path);

      try {
        $("#myplugin_recovery_modal").modal("show");
        setTimeout(function () {
          $("#myplugin_recovery_target_layer").focus();
        }, 50);
      } catch (e) {
        // If modal isn't available for some reason, still works via sidebar panel.
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

    self._injectPerFileRecoveryButtons = function () {
      // Add a wrench icon button next to EACH file entry (local .gcode), near the existing action icons.
      var root = $("#files");
      if (!root.length) return false;

      // Heuristic: file rows commonly have an action button group; we append our button to that group.
      var groups = root.find(".btn-group");
      if (!groups.length) return false;

      groups.each(function () {
        var group = $(this);
        if (group.find(".myplugin-recovery-btn").length) return;

        // Find the closest row element that has Knockout data attached.
        var row = group.closest("li, tr, .file, .entry").get(0);
        if (!row) return;

        var data = null;
        try {
          data = ko.dataFor(row);
        } catch (e) {
          data = null;
        }
        var path = self._extractLocalPathFromFileObject(data);
        if (!path) return;

        // Limit to gcode-like files (still allow ".gco" variants).
        var lower = (path || "").toLowerCase();
        if (!(lower.endsWith(".gcode") || lower.endsWith(".gco") || lower.endsWith(".g"))) return;

        // Button (wrench icon). Supports both Bootstrap2 glyphicons (icon-*) and FontAwesome (fa-*).
        var btn = $(
          '<a href="javascript:void(0)" class="btn btn-mini myplugin-recovery-btn" title="Generate recovery G-code from this file">' +
            '<i class="icon-wrench fa fa-wrench"></i>' +
          "</a>"
        );

        btn.on("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          self.openRecoveryDialogForPath(path);
        });

        group.append(btn);
      });

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
      // Keep trying because the file list can re-render and lose injected buttons.
      self._injectPerFileRecoveryButtons();
      if (tries > 60) {
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



from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


_CURA_LAYER_RE = re.compile(r"^;LAYER:(\d+)\s*$")
_PRUSA_LAYER_RE = re.compile(r"^;\s*layer\s+(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class RecoveryResult:
    output_gcode: str
    detected_layer_marker_style: str


class RecoveryError(RuntimeError):
    pass


def _split_comment(line: str) -> tuple[str, str]:
    """
    Returns (code, comment_including_semicolon_or_empty).
    """
    code, sep, comment = line.partition(";")
    if not sep:
        return line.rstrip("\n"), ""
    return code.rstrip(), ";" + comment.rstrip("\n")


def _is_move_with_xy(code: str) -> bool:
    up = code.upper()
    if not (up.startswith("G0") or up.startswith("G1")):
        return False
    # True "XY move" if it specifies X or Y
    return (" X" in up) or (" Y" in up)


def _find_z(code: str) -> Optional[float]:
    # Simple parse: Z<number>, supports negatives/decimals.
    m = re.search(r"(?:^|\s)Z(-?\d+(?:\.\d+)?)", code, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _layer_number_from_line(line: str) -> tuple[Optional[int], Optional[str]]:
    if (m := _CURA_LAYER_RE.match(line)):
        return int(m.group(1)), "cura"
    if (m := _PRUSA_LAYER_RE.match(line)):
        return int(m.group(1)), "prusa"
    return None, None


def _find_layer_index(lines: list[str], target_layer: int) -> tuple[int, str]:
    last_style: Optional[str] = None
    for i, line in enumerate(lines):
        ln, style = _layer_number_from_line(line.rstrip("\n"))
        if style:
            last_style = style
        if ln == target_layer:
            return i, style or (last_style or "unknown")
    raise RecoveryError(
        f"Target layer {target_layer} not found. "
        f"Expected markers like ';LAYER:{target_layer}' (Cura/Orca/Bambu) or '; layer {target_layer}' (PrusaSlicer)."
    )


def _find_header_end(lines: list[str]) -> int:
    """
    Header is everything before the first layer marker (layer 0 preferred),
    otherwise before the first G0/G1 movement.
    """
    for i, line in enumerate(lines):
        ln, _ = _layer_number_from_line(line.rstrip("\n"))
        if ln == 0:
            return i
    for i, line in enumerate(lines):
        code, _ = _split_comment(line)
        if _is_move_with_xy(code) or (code.strip().upper().startswith(("G0", "G1")) and " Z" in code.upper()):
            return i
    return 0


def _rewrite_g28_no_z(line: str) -> str:
    code, comment = _split_comment(line)
    stripped = code.strip()
    up = stripped.upper()
    if not up.startswith("G28"):
        return line.rstrip("\n")

    # Preserve explicit X/Y homing, but never Z; default to X Y if home-all or Z-only.
    tokens = stripped.split()
    axes = [t.upper() for t in tokens[1:]]

    keep_xy = []
    for ax in axes:
        if ax.startswith("X"):
            keep_xy.append("X")
        elif ax.startswith("Y"):
            keep_xy.append("Y")

    if not axes or not keep_xy:
        new_cmd = "G28 X Y"
    else:
        # Dedup while preserving X then Y order
        ordered = []
        for a in ("X", "Y"):
            if a in keep_xy:
                ordered.append(a)
        new_cmd = "G28 " + " ".join(ordered)

    if comment:
        return f"{new_cmd} {comment}"
    return new_cmd


def generate_recovery_gcode(
    source_gcode: str,
    target_layer: int,
    *,
    safety_z: Optional[float] = None,
) -> RecoveryResult:
    """
    Generates a "recovery" gcode that resumes at target_layer.

    - Preserves header (temps, units, absolute mode, etc.)
    - Rewrites G28 in header to avoid Z homing (G28 -> G28 X Y)
    - Strips all lines between header end and target layer marker
    - Injects G92 E0 before the resume layer
    - Injects a safe Z lift before the first X/Y move of the resume layer
    """
    if target_layer < 0:
        raise RecoveryError("target_layer must be >= 0")

    lines = source_gcode.splitlines(True)  # keep newlines
    header_end = _find_header_end(lines)
    target_idx, style = _find_layer_index(lines, target_layer)

    if target_idx < header_end:
        raise RecoveryError(
            f"Target layer {target_layer} occurs inside the detected header. "
            f"Header_end={header_end}, target_idx={target_idx}. "
            f"Try a higher target layer."
        )

    # Header (modified)
    out_lines: list[str] = []
    for line in lines[:header_end]:
        rewritten = _rewrite_g28_no_z(line)
        out_lines.append(rewritten + "\n" if not rewritten.endswith("\n") else rewritten)

    # Inject extruder reset right before the target layer marker
    out_lines.append("; --- RECOVERY INSERT: reset extruder ---\n")
    out_lines.append("G92 E0\n")

    # Resume segment: from target layer marker to end, with safety Z inserted before first XY move
    resume_lines = lines[target_idx:]

    computed_z: Optional[float] = None
    for line in resume_lines[:200]:
        code, _ = _split_comment(line)
        z = _find_z(code)
        if z is not None:
            computed_z = z
            break

    if safety_z is None:
        if computed_z is not None:
            safety_z_to_use = computed_z + 5.0
        else:
            safety_z_to_use = 50.0
    else:
        safety_z_to_use = float(safety_z)

    inserted_safe_z = False
    for line in resume_lines:
        code, comment = _split_comment(line)
        if (not inserted_safe_z) and _is_move_with_xy(code):
            out_lines.append("; --- RECOVERY INSERT: safety Z lift ---\n")
            # Use G1 to be broadly compatible; absolute/relative is preserved by header.
            out_lines.append(f"G1 Z{safety_z_to_use:.3f} F900\n")
            inserted_safe_z = True

        # Safety: never emit an explicit Z homing command anywhere (AC2).
        if code.strip().upper().startswith("G28") and "Z" in code.upper():
            # Keep X/Y homing at most.
            out_lines.append(_rewrite_g28_no_z(line) + "\n")
            continue

        # Otherwise, passthrough line as-is.
        out_lines.append(line if line.endswith("\n") else (line + "\n"))

    return RecoveryResult(output_gcode="".join(out_lines), detected_layer_marker_style=style)



from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_CURA_LAYER_RE = re.compile(r"^;LAYER:(\d+)\s*$")
_PRUSA_LAYER_RE = re.compile(r"^;\s*layer\s+(\d+)\s*$", re.IGNORECASE)

# Common in Bambu Studio / OrcaSlicer: layer transitions as markers without explicit numbers.
_LAYER_CHANGE_RE = re.compile(r"^;\s*LAYER_CHANGE\s*$", re.IGNORECASE)

# Also common in Bambu/Orca comments
_COMMENT_Z_RE = re.compile(r"^;\s*Z:(-?\d+(?:\.\d+)?)\s*$", re.IGNORECASE)


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
    return (" X" in up) or (" Y" in up)


def _find_z_in_gcode(code: str) -> Optional[float]:
    m = re.search(r"(?:^|\s)Z(-?\d+(?:\.\d+)?)", code, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _find_z_in_comment(line: str) -> Optional[float]:
    # Entire line comment like ";Z:12.34"
    m = _COMMENT_Z_RE.match(line.strip("\n"))
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
    """
    Returns (line_index, style).

    Styles supported:
    - cura: ";LAYER:<n>"
    - prusa: "; layer <n>"
    - layer_change: count occurrences of ";LAYER_CHANGE" as layers starting from 0
    """
    last_style: Optional[str] = None
    layer_change_count = -1

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")

        if _LAYER_CHANGE_RE.match(line):
            layer_change_count += 1
            last_style = "layer_change"
            if layer_change_count == target_layer:
                return i, "layer_change"

        ln, style = _layer_number_from_line(line)
        if style:
            last_style = style
        if ln == target_layer:
            return i, style or (last_style or "unknown")

    raise RecoveryError(
        f"Target layer {target_layer} not found. Expected markers like:\n"
        f"- ';LAYER:{target_layer}' (Cura)\n"
        f"- '; layer {target_layer}' (PrusaSlicer)\n"
        f"- the {target_layer}th ';LAYER_CHANGE' marker (Bambu/Orca counting from 0)"
    )


def _find_header_end(lines: list[str]) -> int:
    """
    Header is everything before the first layer marker (layer 0 preferred),
    otherwise before the first movement.
    """
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        ln, _ = _layer_number_from_line(line)
        if ln == 0:
            return i
        if _LAYER_CHANGE_RE.match(line):
            return i

    for i, raw in enumerate(lines):
        code, _ = _split_comment(raw)
        up = code.strip().upper()
        if _is_move_with_xy(code) or (up.startswith(("G0", "G1")) and " Z" in up):
            return i
    return 0


def _rewrite_g28_no_z(line: str) -> str:
    code, comment = _split_comment(line)
    stripped = code.strip()
    up = stripped.upper()
    if not up.startswith("G28"):
        return line.rstrip("\n")

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
    if target_layer < 0:
        raise RecoveryError("target_layer must be >= 0")

    lines = source_gcode.splitlines(True)
    header_end = _find_header_end(lines)
    target_idx, style = _find_layer_index(lines, target_layer)

    if target_idx < header_end:
        raise RecoveryError(
            f"Target layer {target_layer} occurs inside the detected header. "
            f"Header_end={header_end}, target_idx={target_idx}. Try a higher target layer."
        )

    out_lines: list[str] = []

    # Header (modified: no Z homing)
    for raw in lines[:header_end]:
        rewritten = _rewrite_g28_no_z(raw)
        out_lines.append(rewritten + "\n" if not rewritten.endswith("\n") else rewritten)

    # Inject extruder reset right before resume marker
    out_lines.append("; --- OCTO RESUME INSERT: reset extruder ---\n")
    out_lines.append("G92 E0\n")

    resume_lines = lines[target_idx:]

    # Compute a reasonable safety Z:
    computed_z: Optional[float] = None
    for raw in resume_lines[:300]:
        # First try comment Z like ";Z:12.3", then gcode Z parameter.
        zc = _find_z_in_comment(raw)
        if zc is not None:
            computed_z = zc
            break
        code, _ = _split_comment(raw)
        zg = _find_z_in_gcode(code)
        if zg is not None:
            computed_z = zg
            break

    if safety_z is None:
        safety_z_to_use = (computed_z + 5.0) if (computed_z is not None) else 50.0
    else:
        safety_z_to_use = float(safety_z)

    inserted_safe_z = False
    for raw in resume_lines:
        code, _comment = _split_comment(raw)
        up = code.strip().upper()

        if (not inserted_safe_z) and _is_move_with_xy(code):
            out_lines.append("; --- OCTO RESUME INSERT: safety Z lift ---\n")
            out_lines.append(f"G1 Z{safety_z_to_use:.3f} F900\n")
            inserted_safe_z = True

        # Never emit Z-homing anywhere.
        if up.startswith("G28") and "Z" in up:
            out_lines.append(_rewrite_g28_no_z(raw) + "\n")
            continue

        out_lines.append(raw if raw.endswith("\n") else (raw + "\n"))

    return RecoveryResult(output_gcode="".join(out_lines), detected_layer_marker_style=style)



"""SMPTE timecode utilities with Drop-Frame / Non-Drop-Frame support.

Ported from the reference hls_toolkit.time_utils. Uses Fraction arithmetic
to avoid the rounding drift (e.g. 5.972633 / 6.006011 instead of a uniform
6.006000) that comes from treating 29.97 as a decimal instead of 30000/1001.
"""
from fractions import Fraction
import re


def parse_fps(fps_str: str):
    """Parse an FPS string. Returns (fps: Fraction, is_drop_frame: bool).

    Supports '24', '25', '30000/1001', '2997/125', optional 'DF' suffix.
    """
    df = False
    fps_clean = str(fps_str).strip()
    if fps_clean.upper().endswith("DF"):
        df = True
        fps_clean = fps_clean[:-2].strip()
    fps = Fraction(fps_clean)
    return fps, df


def parse_timecode(tc: str):
    """Parse 'HH:MM:SS:FF' or 'HH:MM:SS;FF' -> (hh, mm, ss, ff)."""
    m = re.match(r"(\d+):(\d+):(\d+)[;:](\d+)", tc)
    if not m:
        raise ValueError(f"Invalid timecode: {tc}")
    return tuple(map(int, m.groups()))


def _ndf_tc_to_frames(hh, mm, ss, ff, fps: Fraction) -> Fraction:
    return (hh * 3600 + mm * 60 + ss) * fps + ff


def _df_tc_to_frames(hh, mm, ss, ff, fps: Fraction) -> int:
    """Drop-frame timecode -> total frames (SMPTE rules for 29.97 / 59.94)."""
    fps_float = float(fps)
    if abs(fps_float - 29.97) < 0.01:
        nominal_fps, drop = 30, 2
    elif abs(fps_float - 59.94) < 0.01:
        nominal_fps, drop = 60, 4
    else:
        raise ValueError(f"Unsupported DF fps={fps}")
    if ss == 0 and ff < drop and mm % 10 != 0:
        # These frame numbers don't exist in DF; clamp.
        ff = drop
    total_minutes = hh * 60 + mm
    total_frames = (total_minutes * 60 + ss) * nominal_fps + ff
    num_drops = total_minutes - total_minutes // 10
    total_frames -= num_drops * drop
    return total_frames


def timecode_to_frame(tc: str, fps_str: str) -> int:
    """Convert timecode -> integer frame number (DF and NDF aware)."""
    fps, df = parse_fps(fps_str)
    hh, mm, ss, ff = parse_timecode(tc)
    is_2997_family = abs(float(fps) - 29.97) < 0.01 or abs(float(fps) - 59.94) < 0.01
    if df or is_2997_family:
        return _df_tc_to_frames(hh, mm, ss, ff, fps)
    return int(round(_ndf_tc_to_frames(hh, mm, ss, ff, fps)))


def timecode_to_seconds(tc: str, fps_str: str) -> Fraction:
    """Convert timecode -> seconds (exact Fraction)."""
    fps, df = parse_fps(fps_str)
    frames = timecode_to_frame(tc, fps_str)
    return Fraction(frames) / fps


def seconds_to_timecode(seconds, fps_str: str, drop_frame_tc_format=False) -> str:
    """Convert seconds -> 'HH:MM:SS:FF' (or ';FF' for drop-frame)."""
    fps, df_from_str = parse_fps(fps_str)
    df = drop_frame_tc_format or df_from_str
    total_frames = int(round(Fraction(seconds) * fps))

    if df:
        fps_float = float(fps)
        if abs(fps_float - 29.97) < 0.01:
            nominal_fps, drop = 30, 2
        elif abs(fps_float - 59.94) < 0.01:
            nominal_fps, drop = 60, 4
        else:
            raise ValueError(f"Unsupported DF fps={fps}")
        d, R = drop, nominal_fps
        frames = total_frames
        est_minutes = frames // (R * 60)
        comp = frames + d * (est_minutes - est_minutes // 10)
        hh = comp // (R * 3600)
        comp %= R * 3600
        mm = comp // (R * 60)
        comp %= R * 60
        ss = comp // R
        ff = comp % R
        return f"{hh:02d}:{mm:02d}:{ss:02d};{ff:02d}"

    nominal = int(round(float(fps)))
    hh = total_frames // (nominal * 3600)
    rem = total_frames % (nominal * 3600)
    mm = rem // (nominal * 60)
    rem %= nominal * 60
    ss = rem // nominal
    ff = rem % nominal
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

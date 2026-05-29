"""Subtitle processing: convert -> VTT, clip+offset cues onto the compacted
output timeline, then segment aligned EXACTLY to the video segment boundaries
(so subtitle EXTINF values match the video, including the short segments that
appear at clip transitions).
"""
import math
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional


def convert_subtitle_to_vtt(ffmpeg_path: str, subtitle_url: str, output_vtt_path: str, timeout: int = 120) -> bool:
    """Convert any subtitle input to a single WebVTT file."""
    cmd = [ffmpeg_path, "-y", "-i", subtitle_url, "-c:s", "webvtt", output_vtt_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and Path(output_vtt_path).exists():
            logging.info(f"Subtitle converted to VTT: {output_vtt_path}")
            return True
        logging.error(f"Subtitle VTT conversion failed (rc={result.returncode}): {result.stderr[-400:]}")
        return False
    except Exception as e:
        logging.error(f"Subtitle VTT conversion error: {e}")
        return False


def _parse_vtt_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(ts)
    except (ValueError, IndexError):
        return 0.0


def _format_vtt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h = total_ms // 3600000
    total_ms %= 3600000
    m = total_ms // 60000
    total_ms %= 60000
    s = total_ms // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_vtt_cues(vtt_path: Path) -> List[Tuple[float, float, str]]:
    """Parse a WebVTT file -> list of (start_sec, end_sec, text) in source time."""
    cues = []
    try:
        text = Path(vtt_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logging.error(f"Cannot read VTT {vtt_path}: {e}")
        return cues

    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block or block.startswith("WEBVTT") or block.startswith("NOTE") or "X-TIMESTAMP-MAP" in block:
            continue
        block_lines = block.splitlines()
        ts_idx = next((i for i, l in enumerate(block_lines) if "-->" in l), None)
        if ts_idx is None:
            continue
        ts_parts = block_lines[ts_idx].split("-->")
        if len(ts_parts) < 2:
            continue
        try:
            start = _parse_vtt_time(ts_parts[0])
            end = _parse_vtt_time(ts_parts[1].strip().split()[0])
        except (ValueError, IndexError):
            continue
        body = [l for l in block_lines[ts_idx + 1:] if l.strip()]
        if body and end > start:
            cues.append((start, end, "\n".join(body)))
    return cues


def build_merged_timeline_cues(cues: List[Tuple[float, float, str]],
                               clips_sec: List[Tuple[float, float]]) -> List[Tuple[float, float, str]]:
    """Clip each cue to each clip window and offset onto the compacted timeline.

    clips_sec: list of (start_orig, end_orig) source-time windows, in order.
    Returns cues with timestamps on the merged (compacted) output timeline.
    """
    if not clips_sec:
        return list(cues)

    merged = []
    cumulative = 0.0
    for (cs, ce) in clips_sec:
        clip_dur = ce - cs
        if clip_dur <= 0:
            continue
        for (start, end, txt) in cues:
            ov_start = max(start, cs)
            ov_end = min(end, ce)
            if ov_start < ov_end:
                merged.append((
                    ov_start - cs + cumulative,
                    ov_end - cs + cumulative,
                    txt,
                ))
        cumulative += clip_dur

    merged.sort(key=lambda c: c[0])
    return merged


def segment_vtt_for_hls(merged_cues: List[Tuple[float, float, str]],
                        video_segments: List[Tuple[float, float, str, int]],
                        output_dir: str,
                        lang: str = "en",
                        start_number: int = 1,
                        mpegts_base_90k: int = 126000) -> Optional[str]:
    """Write one VTT per video segment (aligned to video segment durations) and
    a matching HLS playlist. Returns the playlist path.

    Each VTT carries an X-TIMESTAMP-MAP so the cue times sync to the video PTS:
      MPEGTS = mpegts_base_90k + round(seg_start * 90000)
      LOCAL  = 00:00:00.000      (cue times are relative to the segment start)
    Without this header players show subtitles only at the start and then drop
    them — which is the desync the reference fixes.
    """
    if not video_segments:
        logging.error("No video segments for subtitle alignment")
        return None

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extinf_values = []
    seg_filenames = []

    for seg_idx, (seg_start, seg_end, _f, _l) in enumerate(video_segments):
        seg_dur = seg_end - seg_start
        seg_num = start_number + seg_idx
        out_filename = f"sub_{lang}_{seg_num:05d}.vtt"
        out_filepath = output_path / out_filename

        mpegts = mpegts_base_90k + int(round(seg_start * 90000))
        body = [f"WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:{mpegts}\n\n"]
        for (cstart, cend, ctext) in merged_cues:
            if cstart < seg_end and cend > seg_start:
                rel_start = max(cstart - seg_start, 0.0)
                rel_end = min(cend - seg_start, seg_dur)
                if rel_end > rel_start:
                    body.append(f"{_format_vtt_time(rel_start)} --> {_format_vtt_time(rel_end)}\n{ctext}\n\n")
        out_filepath.write_text("".join(body), encoding="utf-8")
        extinf_values.append(seg_dur)
        seg_filenames.append(out_filename)

    if not extinf_values:
        return None

    targetduration = math.ceil(max(extinf_values))
    playlist_path = output_path / f"sub_{lang}.m3u8"
    pl = [
        "#EXTM3U\n",
        "#EXT-X-VERSION:3\n",
        f"#EXT-X-TARGETDURATION:{targetduration}\n",
        f"#EXT-X-MEDIA-SEQUENCE:{start_number}\n",
        "#EXT-X-PLAYLIST-TYPE:VOD\n",
    ]
    for dur, fname in zip(extinf_values, seg_filenames):
        pl.append(f"#EXTINF:{dur:.6f},\n{fname}\n")
    pl.append("#EXT-X-ENDLIST\n")
    playlist_path.write_text("".join(pl), encoding="utf-8")
    logging.info(f"Subtitle playlist: {playlist_path.name} ({len(seg_filenames)} segs, TARGETDURATION={targetduration})")
    return str(playlist_path)

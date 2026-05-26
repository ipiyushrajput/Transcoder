import math
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional


def convert_subtitle_to_vtt(ffmpeg_path: str, subtitle_url: str, output_vtt_path: str, timeout: int = 120) -> bool:
    """Convert any subtitle format to a single WebVTT file using FFmpeg."""
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
    """Parse VTT/SRT timestamp string -> seconds. Supports HH:MM:SS.mmm and MM:SS.mmm."""
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


def parse_vtt_cues(vtt_path: Path) -> List[Tuple[float, float, str]]:
    """Parse a WebVTT file. Returns list of (start_sec, end_sec, cue_text) tuples."""
    cues = []
    try:
        text = vtt_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logging.error(f"Cannot read VTT file {vtt_path}: {e}")
        return cues

    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("WEBVTT") or block.startswith("NOTE"):
            continue
        lines = block.splitlines()
        ts_idx = None
        for i, line in enumerate(lines):
            if "-->" in line:
                ts_idx = i
                break
        if ts_idx is None:
            continue
        ts_parts = lines[ts_idx].split("-->")
        if len(ts_parts) < 2:
            continue
        try:
            start = _parse_vtt_time(ts_parts[0])
            end_part = ts_parts[1].strip().split()[0]
            end = _parse_vtt_time(end_part)
        except (ValueError, IndexError):
            continue
        text_lines = [l for l in lines[ts_idx + 1:] if l.strip()]
        if text_lines:
            cues.append((start, end, "\n".join(text_lines)))

    return cues


def _format_vtt_time(seconds: float) -> str:
    """Format float seconds -> VTT timestamp HH:MM:SS.mmm."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def segment_vtt_for_hls(
    vtt_path: Path,
    video_segments: List[Tuple[float, float, str, int]],
    output_dir: str,
    lang: str = "en",
    start_number: int = 1,
) -> Optional[str]:
    """
    Segment a WebVTT file aligned exactly to video segment boundaries.

    video_segments: list of (seg_start_sec, seg_end_sec, seg_filename, line_idx)
    Returns the path to the generated subtitle HLS playlist, or None on failure.
    """
    if not vtt_path.exists():
        logging.error(f"VTT source not found: {vtt_path}")
        return None
    if not video_segments:
        logging.error("No video segments provided for subtitle alignment")
        return None

    cues = parse_vtt_cues(vtt_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extinf_values = []
    seg_filenames = []

    for seg_idx, (seg_start, seg_end, _seg_file, _) in enumerate(video_segments):
        seg_dur = seg_end - seg_start
        seg_num = start_number + seg_idx
        out_filename = f"sub_{lang}_{seg_num:05d}.vtt"
        out_filepath = output_path / out_filename

        seg_cues = []
        for cue_start, cue_end, cue_text in cues:
            if cue_start < seg_end and cue_end > seg_start:
                rel_start = max(cue_start - seg_start, 0.0)
                rel_end = min(cue_end - seg_start, seg_dur)
                if rel_end > rel_start:
                    seg_cues.append((rel_start, rel_end, cue_text))

        vtt_lines = ["WEBVTT\n\n"]
        for i, (rel_start, rel_end, cue_text) in enumerate(seg_cues, 1):
            ts_s = _format_vtt_time(rel_start)
            ts_e = _format_vtt_time(rel_end)
            vtt_lines.append(f"{i}\n{ts_s} --> {ts_e}\n{cue_text}\n\n")

        out_filepath.write_text("".join(vtt_lines), encoding="utf-8")
        extinf_values.append(seg_dur)
        seg_filenames.append(out_filename)

    if not extinf_values:
        logging.error("No segments generated for subtitle playlist")
        return None

    targetduration = math.ceil(max(extinf_values))
    playlist_name = f"sub_{lang}.m3u8"
    playlist_path = output_path / playlist_name

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
    logging.info(f"Subtitle playlist: {playlist_path} ({len(seg_filenames)} segments, TARGETDURATION={targetduration})")
    return str(playlist_path)

import os
import re
import json
import uuid
import shutil
import logging
import tempfile
import subprocess
import threading
from fractions import Fraction
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from esam_processor import (
    parse_esam_scc_xml,
    process_esam_on_output,
    parse_variant_segments,
    remap_esam_events_for_merged_clips,
)
from s3_uploader import build_s3_client, start_live_upload_watcher, upload_directory_to_s3
from subtitle_processor import (
    convert_subtitle_to_vtt,
    parse_vtt_cues,
    build_merged_timeline_cues,
    segment_vtt_for_hls,
)
import time_utils

# In-memory job registry
_vod_jobs = {}
_vod_locks = {}
_executor = ThreadPoolExecutor(max_workers=4)

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR = os.path.join(_BACKEND_DIR, "logs")
os.makedirs(_LOGS_DIR, exist_ok=True)


# ----------------------------------------------------------------------------
# ffprobe helpers
# ----------------------------------------------------------------------------
def _get_video_info(input_url: str) -> dict:
    """Return {'duration': float, 'fps': Fraction} using a single ffprobe call."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate", "-show_entries", "format=duration",
        "-of", "json", input_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout or "{}")
        dur_str = data.get("format", {}).get("duration")
        duration = float(dur_str) if dur_str else 0.0
        fr_str = "25/1"
        streams = data.get("streams", [])
        if streams:
            fr_str = streams[0].get("avg_frame_rate", "25/1")
        fps = Fraction(fr_str) if fr_str and fr_str != "0/0" else Fraction(25, 1)
        return {"duration": duration, "fps": fps}
    except Exception as e:
        logging.warning(f"ffprobe video info failed: {e}; defaulting to 25fps")
        return {"duration": 0.0, "fps": Fraction(25, 1)}


# ----------------------------------------------------------------------------
# Clip helpers
# ----------------------------------------------------------------------------
def _normalize_clips(clips: list, fps: Fraction, total_duration: float) -> List[Tuple[float, float]]:
    """Convert UI clips (SMPTE timecodes) to (start_sec, end_sec) source windows.

    If no clips are given, the whole video becomes a single clip — this unifies
    the pipeline so every output is frame-precise.
    """
    fps_str = str(fps)
    out = []
    for clip in clips or []:
        try:
            s = float(time_utils.timecode_to_seconds(clip["start_timecode"], fps_str))
            e = float(time_utils.timecode_to_seconds(clip["end_timecode"], fps_str))
        except Exception as ex:
            logging.warning(f"Skipping invalid clip {clip}: {ex}")
            continue
        if e > s:
            out.append((s, e))
    if not out:
        end = total_duration if total_duration > 0 else None
        if end is None:
            # Unknown duration; let ffmpeg read to EOF via a single open-ended clip.
            out.append((0.0, 0.0))
        else:
            out.append((0.0, end))
    return out


def _clip_gop_offset_seconds(start_sec: float, fps: Fraction, gop_frames: int) -> float:
    """Frames to shift the first keyframe so the clip's GOPs align to the global
    GOP grid (mirrors the reference clip_gop_offsets logic)."""
    start_frame = int(round(start_sec * float(fps)))
    offset_frames = (gop_frames - start_frame % gop_frames) % gop_frames
    return offset_frames / float(fps)


# ----------------------------------------------------------------------------
# FFmpeg command builders
# ----------------------------------------------------------------------------
def _build_clip_command(input_url: str, clip_idx: int, start_sec: float, end_sec: float,
                        variants: list, fps: Fraction, gop_frames: int, gop_offset: float,
                        preset: str, tmp_dir: str, deinterlace: bool,
                        use_open_ended: bool, ffmpeg_path: str) -> Tuple[list, dict, str]:
    """Encode one clip into one MP4 per variant + one audio MP4 (single command).

    Returns (cmd, {variant_name: video_path}, audio_path).
    """
    fps_str = f"{fps.numerator}/{fps.denominator}"
    gop_dur = gop_frames / float(fps)  # exact segment duration, e.g. 180/(30000/1001)=6.006

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-thread_queue_size", "1024"]
    # Input seeking (-ss/-t before -i) resets timestamps to 0 -> each clip starts
    # with a fresh IDR, which is what produces clean splits at clip boundaries.
    cmd += ["-ss", f"{start_sec:.3f}"]
    if not use_open_ended:
        cmd += ["-t", f"{max(0.0, end_sec - start_sec):.3f}"]
    cmd += ["-i", input_url]

    n = len(variants)
    fc = [f"[0:v]split={n}{''.join(f'[v{i}]' for i in range(n))}"]
    for i, v in enumerate(variants):
        w, h = v["width"], v["height"]
        deint = "yadif=mode=0:parity=auto:deint=1," if deinterlace else ""
        fc.append(
            f"[v{i}]{deint}scale=w={w}:h={h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}out]"
        )
    cmd += ["-filter_complex", "; ".join(fc)]

    if gop_offset > 0.001:
        force_kf = f"expr:gte(t,{gop_offset:.3f}+n_forced*{gop_dur:.3f})"
    else:
        force_kf = f"expr:gte(t,n_forced*{gop_dur:.3f})"

    video_paths = {}
    for i, v in enumerate(variants):
        name = f"{v.get('height', 'v' + str(i))}p"
        codec = v.get("video_codec", "libx264")
        bitrate = int(v.get("video_bitrate", 2000000))
        ref = int(v.get("reference_frames", 4))
        profile = v.get("profile", "main")
        level = v.get("level", "4.1")
        out_path = os.path.join(tmp_dir, f"clip_{clip_idx:03d}_{name}.mp4")
        video_paths[name] = out_path

        cmd += ["-map", f"[v{i}out]", "-an"]
        cmd += ["-c:v", codec]
        if codec == "libx264":
            cmd += ["-x264-params",
                    f"rc-lookahead=32:bframes=3:ref={ref}:nal-hrd=cbr:"
                    f"bitrate={bitrate // 1000}:vbv-maxrate={bitrate // 1000}:vbv-bufsize={bitrate // 500}",
                    "-profile:v", profile, "-level:v", level]
        elif codec == "libx265":
            cmd += ["-x265-params",
                    f"rc-lookahead=32:bframes=3:ref={ref}:"
                    f"vbv-maxrate={bitrate // 1000}:vbv-bufsize={bitrate // 500}",
                    "-tag:v", "hvc1"]
        cmd += [
            "-b:v", str(bitrate),
            "-r", fps_str,
            "-preset", preset,
            "-force_key_frames", force_kf,
            "-pix_fmt", "yuv420p",
            "-color_range", "tv",
            "-avoid_negative_ts", "make_zero",
            out_path,
        ]

    # Single shared audio track.
    a = variants[0]
    audio_path = os.path.join(tmp_dir, f"clip_{clip_idx:03d}_audio.mp4")
    cmd += [
        "-map", "0:a:0?", "-vn",
        "-c:a", a.get("audio_codec", "aac"),
        "-ar", str(a.get("sample_rate", 48000)),
        "-b:a", str(a.get("audio_bitrate", 128000)),
        "-avoid_negative_ts", "make_zero",
        audio_path,
    ]
    return cmd, video_paths, audio_path


def _build_concat_merge_command(clip_paths: list, out_path: str, tmp_dir: str,
                                tag: str, ffmpeg_path: str) -> list:
    """Concat (stream-copy) per-clip MP4s into one continuous file."""
    list_path = os.path.join(tmp_dir, f"concat_{tag}.txt")
    with open(list_path, "w") as f:
        f.write("ffconcat version 1.0\n")
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    return [
        ffmpeg_path, "-y", "-hide_banner", "-safe", "0",
        "-i", list_path, "-c", "copy", "-avoid_negative_ts", "make_zero", out_path,
    ]


def _build_hls_command(merged_video: str, merged_audio: Optional[str], name: str,
                       output_dir: str, segment_size: int, hls_playlist_type: str,
                       hls_flags: str, ffmpeg_path: str) -> list:
    """Segment a merged variant with -c copy. Splits land on the keyframes laid
    down during the per-clip encode -> uniform GOP segments + short segments at
    clip boundaries (matching the reference)."""
    cmd = [ffmpeg_path, "-y", "-hide_banner", "-i", merged_video]
    if merged_audio and os.path.exists(merged_audio):
        cmd += ["-i", merged_audio, "-map", "0:v:0", "-c:v", "copy", "-map", "1:a:0", "-c:a", "copy"]
    else:
        cmd += ["-map", "0:v:0", "-c:v", "copy", "-an"]
    cmd += [
        "-f", "hls",
        "-start_number", "1",
        "-hls_time", str(segment_size),
        "-hls_playlist_type", hls_playlist_type or "vod",
        "-hls_flags", hls_flags or "independent_segments",
        "-hls_segment_type", "mpegts",
        "-hls_segment_filename", os.path.join(output_dir, f"segment_{name}_%05d.ts"),
        os.path.join(output_dir, f"variant_{name}.m3u8"),
    ]
    return cmd


# ----------------------------------------------------------------------------
# Master playlist
# ----------------------------------------------------------------------------
def _h264_profile_idc(profile_name: str) -> str:
    p = str(profile_name).lower()
    if p in ("100", "high"):
        return "64"
    if p in ("77", "main"):
        return "4d"
    return "42"


def _codecs_string(variant: dict) -> str:
    codec = variant.get("video_codec", "libx264")
    if codec == "libx265":
        return "hvc1.1.6.L93.B0,mp4a.40.2"
    profile_idc = _h264_profile_idc(variant.get("profile", "main"))
    try:
        level_int = int(round(float(variant.get("level", "4.1")) * 10))
    except (ValueError, TypeError):
        level_int = 41
    constraint = "40" if profile_idc == "4d" else "00"
    return f"avc1.{profile_idc}{constraint}{level_int:02x},mp4a.40.2"


def _write_master_playlist(master_path: str, variants: list, sub_lang: Optional[str], fps: Fraction):
    lines = ["#EXTM3U\n", "#EXT-X-VERSION:6\n", "#EXT-X-INDEPENDENT-SEGMENTS\n"]
    has_subs = sub_lang is not None
    frame_rate = f"{float(fps):.3f}"
    for v in variants:
        name = f"{v.get('height', 0)}p"
        bw = int(v.get("video_bitrate", 2000000)) + int(v.get("audio_bitrate", 128000))
        parts = [
            f"BANDWIDTH={bw}",
            f"AVERAGE-BANDWIDTH={bw}",
            f'CODECS="{_codecs_string(v)}"',
            f"RESOLUTION={v['width']}x{v['height']}",
            f"FRAME-RATE={frame_rate}",
        ]
        line = "#EXT-X-STREAM-INF:" + ",".join(parts)
        if has_subs:
            line += ',SUBTITLES="subs"'
        lines.append(line + "\n")
        lines.append(f"variant_{name}.m3u8\n")
    if has_subs:
        lines.append(
            f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",'
            f'DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,LANGUAGE="{sub_lang}",URI="sub_{sub_lang}.m3u8"\n'
        )
    Path(master_path).write_text("".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
# Subprocess runner with cancel + progress
# ----------------------------------------------------------------------------
def _run_ffmpeg(cmd: list, log_path: str, pinfo: dict, base_pct: int, span_pct: int,
                expected_seconds: float) -> int:
    """Run an ffmpeg command, streaming to the persistent log, supporting cancel
    via pinfo['cancel'] and updating pinfo['progress_pct'] from the time= output.
    Returns the process return code (or -1 if cancelled)."""
    with open(log_path, "a", errors="replace") as log_f:
        log_f.write(f"\n$ {' '.join(cmd)}\n")
        log_f.flush()
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
        pinfo["current_proc"] = proc

        while proc.poll() is None:
            if pinfo.get("cancel"):
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()
                return -1
            if expected_seconds and expected_seconds > 0:
                elapsed = _tail_time(log_path)
                if elapsed is not None:
                    frac = max(0.0, min(elapsed / expected_seconds, 1.0))
                    pinfo["progress_pct"] = min(99, base_pct + int(span_pct * frac))
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    pinfo["progress_pct"] = min(99, base_pct + span_pct)
    return proc.returncode


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def _tail_time(log_path: str) -> Optional[float]:
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            chunk = f.read().decode("utf-8", errors="replace")
        matches = _TIME_RE.findall(chunk)
        if matches:
            h, m, s = matches[-1]
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
def start_vod_job(job_config: dict, db_update_callback=None) -> dict:
    job_id = job_config.get("job_id") or str(uuid.uuid4())
    name = job_config.get("name", job_id)
    logging.info(f"[VOD:{name}] Starting job {job_id}")

    tmp_dir = tempfile.mkdtemp(prefix=f"vod_{job_id[:8]}_")
    dest = job_config.get("output_destination", "LOCAL").upper()
    _local_path = job_config.get("local_path", "").strip()
    output_dir = _local_path if (dest == "LOCAL" and _local_path) else os.path.join(tmp_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    log_path = os.path.join(_LOGS_DIR, f"vod_{job_id}.log")
    Path(log_path).write_text(f"--- VOD job {name} ({job_id}) started {datetime.utcnow().isoformat()} ---\n")

    lock = threading.Lock()
    _vod_locks[job_id] = lock
    _vod_jobs[job_id] = {
        "job_config": job_config,
        "tmp_dir": tmp_dir,
        "output_dir": output_dir,
        "log_path": log_path,
        "status": "RUNNING",
        "progress_pct": 0,
        "started_at": datetime.utcnow().isoformat(),
        "cancel": False,
        "current_proc": None,
    }

    if db_update_callback:
        db_update_callback(job_id, "RUNNING", None)

    _executor.submit(_run_vod_pipeline, job_id, db_update_callback)

    return {
        "success": True,
        "job_id": job_id,
        "status": "RUNNING",
        "playback_url": _build_playback_url(job_config),
        "pid": None,
    }


def _run_vod_pipeline(job_id: str, db_update_callback=None):
    pinfo = _vod_jobs.get(job_id)
    if not pinfo:
        return
    job_config = pinfo["job_config"]
    name = job_config.get("name", job_id)
    output_dir = pinfo["output_dir"]
    log_path = pinfo["log_path"]
    tmp_dir = pinfo["tmp_dir"]
    ffmpeg_path = "ffmpeg"

    observer = handler = periodic = s3_client = None
    status = "FAILED"
    error_msg = ""

    try:
        input_url = job_config["input_url"].strip()
        variants = job_config.get("variants", [])
        if not variants:
            raise RuntimeError("No output variants specified")
        # Highest resolution first (master + reference segments use the top rung).
        variants = sorted(variants, key=lambda v: int(v.get("height", 0)), reverse=True)

        output_type = job_config.get("output_type", "HLS").upper()
        segment_size = int(job_config.get("segment_length", 6))
        master_filename = job_config.get("master_filename", "master")
        preset = job_config.get("preset", "medium")
        hls_playlist_type = job_config.get("hls_playlist_type", "vod")
        hls_flags = job_config.get("hls_flags", "independent_segments")

        info = _get_video_info(input_url)
        fps = info["fps"]
        duration = info["duration"]
        gop_frames = int(round(segment_size * float(fps)))
        if gop_frames <= 0:
            gop_frames = segment_size * 25
        logging.info(f"[VOD:{name}] fps={fps} duration={duration:.3f}s gop_frames={gop_frames}")

        clips_sec = _normalize_clips(job_config.get("clips", []), fps, duration)
        use_open_ended = len(clips_sec) == 1 and clips_sec[0] == (0.0, 0.0)
        total_output_duration = sum(max(0.0, e - s) for s, e in clips_sec) or duration
        pinfo["total_output_duration"] = total_output_duration

        # S3 watcher for real-time upload of segments as they appear.
        dest = job_config.get("output_destination", "LOCAL").upper()
        if dest == "S3":
            try:
                s3_client = build_s3_client()
                observer, handler, periodic = start_live_upload_watcher(
                    output_dir, job_config.get("s3_bucket", ""),
                    job_config.get("s3_path", name).strip("/"), s3_client)
            except Exception as e:
                logging.error(f"[VOD:{name}] S3 watcher failed: {e}")

        if output_type != "HLS":
            # MP4: single encode of the first clip range.
            _run_mp4_pipeline(pinfo, input_url, variants, clips_sec, fps, preset,
                              output_dir, master_filename, ffmpeg_path, use_open_ended)
        else:
            _run_hls_pipeline(pinfo, job_config, input_url, variants, clips_sec, fps,
                              gop_frames, preset, segment_size, hls_playlist_type, hls_flags,
                              master_filename, output_dir, tmp_dir, ffmpeg_path,
                              use_open_ended, total_output_duration)

        if pinfo.get("cancel"):
            status = "STOPPED"
        else:
            status = "COMPLETED"
            pinfo["progress_pct"] = 100

        # Stop watcher and do a final sweep upload.
        _stop_watchers(observer, handler, periodic)
        if dest == "S3" and status == "COMPLETED":
            try:
                client = s3_client or build_s3_client()
                cnt = upload_directory_to_s3(output_dir, job_config.get("s3_bucket", ""),
                                             job_config.get("s3_path", name).strip("/"), client)
                logging.info(f"[VOD:{name}] Final S3 upload: {cnt} files")
            except Exception as e:
                logging.error(f"[VOD:{name}] Final S3 upload error: {e}")

    except Exception as e:
        logging.error(f"[VOD:{name}] Pipeline error: {e}", exc_info=True)
        error_msg = str(e)
        status = "STOPPED" if pinfo.get("cancel") else "FAILED"
        _stop_watchers(observer, handler, periodic)

    # Persist a final status marker so the log is never empty for finished jobs.
    try:
        with open(log_path, "a", errors="replace") as lf:
            lf.write(f"\n--- Transcoder: Status {status} | {datetime.utcnow().isoformat()} ---\n")
            if error_msg:
                lf.write(f"ERROR: {error_msg}\n")
    except Exception:
        pass

    lock = _vod_locks.get(job_id)
    if lock:
        with lock:
            if job_id in _vod_jobs:
                _vod_jobs[job_id]["status"] = status
                _vod_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

    if status == "FAILED" and not error_msg:
        try:
            error_msg = Path(log_path).read_text(errors="replace")[-3000:]
        except Exception:
            pass

    if db_update_callback:
        db_update_callback(job_id, status, None, error_msg if status == "FAILED" else None)

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass
    _vod_jobs.pop(job_id, None)
    _vod_locks.pop(job_id, None)


def _run_hls_pipeline(pinfo, job_config, input_url, variants, clips_sec, fps, gop_frames,
                      preset, segment_size, hls_playlist_type, hls_flags, master_filename,
                      output_dir, tmp_dir, ffmpeg_path, use_open_ended, total_output_duration):
    name = job_config.get("name")
    log_path = pinfo["log_path"]
    num_clips = len(clips_sec)

    # 1) Encode each clip separately into per-variant MP4 + audio MP4.
    #    Each clip starts with a fresh IDR; GOP offset aligns its keyframes to
    #    the global GOP grid so copy-segmentation later yields uniform segments
    #    plus clean short segments at clip transitions.
    per_variant_clips = {f"{v.get('height', 0)}p": [] for v in variants}
    audio_clips = []
    encoded_base = 0.0  # seconds of content encoded so far (for progress)

    for ci, (cs, ce) in enumerate(clips_sec):
        if pinfo.get("cancel"):
            return
        clip_dur = (ce - cs) if not use_open_ended else (total_output_duration or 1.0)
        gop_offset = _clip_gop_offset_seconds(cs, fps, gop_frames)
        cmd, vpaths, apath = _build_clip_command(
            input_url, ci, cs, ce, variants, fps, gop_frames, gop_offset,
            preset, tmp_dir, deinterlace=True, use_open_ended=use_open_ended,
            ffmpeg_path=ffmpeg_path)

        base_pct = int(encoded_base / max(total_output_duration, 0.001) * 60)
        span_pct = max(1, int(clip_dur / max(total_output_duration, 0.001) * 60))
        rc = _run_ffmpeg(cmd, log_path, pinfo, base_pct, span_pct, clip_dur)
        if rc == -1:
            return
        if rc != 0:
            raise RuntimeError(f"Clip {ci} encode failed (rc={rc}); see log")

        for vname, p in vpaths.items():
            per_variant_clips[vname].append(p)
        if os.path.exists(apath):
            audio_clips.append(apath)
        encoded_base += clip_dur

    # 2) Merge clips per variant (+ audio). Single clip => use directly.
    pinfo["progress_pct"] = 62
    merged_video = {}
    for vname, paths in per_variant_clips.items():
        if not paths:
            continue
        if len(paths) == 1:
            merged_video[vname] = paths[0]
        else:
            out = os.path.join(tmp_dir, f"merged_{vname}.mp4")
            rc = _run_ffmpeg(_build_concat_merge_command(paths, out, tmp_dir, vname, ffmpeg_path),
                             log_path, pinfo, 62, 1, 0)
            if rc == -1:
                return
            if rc != 0:
                raise RuntimeError(f"Merge failed for {vname} (rc={rc})")
            merged_video[vname] = out

    merged_audio = None
    if audio_clips:
        if len(audio_clips) == 1:
            merged_audio = audio_clips[0]
        else:
            merged_audio = os.path.join(tmp_dir, "merged_audio.mp4")
            rc = _run_ffmpeg(_build_concat_merge_command(audio_clips, merged_audio, tmp_dir, "audio", ffmpeg_path),
                             log_path, pinfo, 64, 1, 0)
            if rc == -1:
                return
            if rc != 0:
                raise RuntimeError(f"Audio merge failed (rc={rc})")

    # 3) HLS-segment each merged variant with -c copy.
    pinfo["progress_pct"] = 66
    n = len(variants)
    for vi, v in enumerate(variants):
        if pinfo.get("cancel"):
            return
        vname = f"{v.get('height', 0)}p"
        if vname not in merged_video:
            continue
        cmd = _build_hls_command(merged_video[vname], merged_audio, vname, output_dir,
                                 segment_size, hls_playlist_type, hls_flags, ffmpeg_path)
        base = 66 + int(vi / n * 20)
        rc = _run_ffmpeg(cmd, log_path, pinfo, base, max(1, int(20 / n)), 0)
        if rc == -1:
            return
        if rc != 0:
            raise RuntimeError(f"HLS segmentation failed for {vname} (rc={rc})")

    # 4) Reference video segments come from the top (first) variant playlist.
    pinfo["progress_pct"] = 88
    top_name = f"{variants[0].get('height', 0)}p"
    top_playlist = Path(output_dir) / f"variant_{top_name}.m3u8"
    video_segments = []
    if top_playlist.exists():
        _, video_segments, _ = parse_variant_segments(top_playlist)

    # 5) Subtitles: convert -> parse -> clip/offset onto compacted timeline ->
    #    segment aligned to video_segments.
    sub_lang = job_config.get("subtitle_language", "en")
    sub_url = job_config.get("subtitle_url")
    sub_playlist = None
    if sub_url and video_segments:
        vtt_tmp = os.path.join(tmp_dir, f"source_{sub_lang}.vtt")
        if convert_subtitle_to_vtt(ffmpeg_path, sub_url, vtt_tmp):
            cues = parse_vtt_cues(Path(vtt_tmp))
            merged_cues = build_merged_timeline_cues(cues, clips_sec if not use_open_ended else [])
            sub_playlist = segment_vtt_for_hls(merged_cues, video_segments, output_dir, sub_lang)

    # 6) Master playlist.
    pinfo["progress_pct"] = 92
    _write_master_playlist(os.path.join(output_dir, f"{master_filename}.m3u8"),
                           variants, sub_lang if sub_playlist else None, fps)

    # 7) ESAM injection (remapped to compacted timeline, aligned to video_segments).
    if job_config.get("esam_enabled") and job_config.get("esam_scc_xml"):
        events = parse_esam_scc_xml(job_config["esam_scc_xml"])
        if events:
            if not use_open_ended:
                events = remap_esam_events_for_merged_clips(events, clips_sec)
            cnt = process_esam_on_output(output_dir, events, sub_playlist,
                                         mcc_xml=job_config.get("esam_mcc_xml"),
                                         video_segments=video_segments)
            logging.info(f"[VOD:{name}] Injected {cnt} ESAM marker lines")

    pinfo["progress_pct"] = 99


def _run_mp4_pipeline(pinfo, input_url, variants, clips_sec, fps, preset,
                      output_dir, master_filename, ffmpeg_path, use_open_ended):
    """Simple progressive MP4 of the top variant over the first clip range."""
    log_path = pinfo["log_path"]
    v = variants[0]
    cs, ce = clips_sec[0]
    out_file = os.path.join(output_dir, f"{master_filename}.mp4")
    cmd = [ffmpeg_path, "-y", "-hide_banner"]
    cmd += ["-ss", f"{cs:.3f}"]
    if not use_open_ended:
        cmd += ["-t", f"{max(0.0, ce - cs):.3f}"]
    cmd += ["-i", input_url,
            "-c:v", v.get("video_codec", "libx264"),
            "-b:v", str(v.get("video_bitrate", 4000000)),
            "-r", f"{fps.numerator}/{fps.denominator}",
            "-preset", preset, "-pix_fmt", "yuv420p",
            "-c:a", v.get("audio_codec", "aac"),
            "-b:a", str(v.get("audio_bitrate", 128000)),
            "-ar", str(v.get("sample_rate", 48000)),
            out_file]
    dur = (ce - cs) if not use_open_ended else 0
    rc = _run_ffmpeg(cmd, log_path, pinfo, 0, 99, dur)
    if rc == -1:
        return
    if rc != 0:
        raise RuntimeError(f"MP4 encode failed (rc={rc})")


def _stop_watchers(observer, handler, periodic):
    try:
        if periodic:
            periodic.stop()
        if handler:
            handler.stop()
        if observer and observer.is_alive():
            observer.stop()
            observer.join(timeout=5)
    except Exception as e:
        logging.warning(f"Error stopping watchers: {e}")


def _build_playback_url(job_config: dict) -> str:
    dest = job_config.get("output_destination", "LOCAL").upper()
    master = job_config.get("master_filename", "master")
    if dest == "S3":
        cf = job_config.get("s3_cloudfront_domain", "").rstrip("/")
        s3_path = job_config.get("s3_path", "").strip("/")
        if cf:
            return f"{cf}/{s3_path}/{master}.m3u8"
        bucket = job_config.get("s3_bucket", "")
        return f"https://{bucket}.s3.us-east-1.amazonaws.com/{s3_path}/{master}.m3u8"
    elif dest == "MEDIAPACKAGE":
        return job_config.get("mediapackage_url", "")
    local = job_config.get("local_path", "/tmp/output")
    return f"file://{local}/{master}.m3u8"


def stop_vod_job(job_id: str, db_update_callback=None) -> dict:
    pinfo = _vod_jobs.get(job_id)
    if not pinfo:
        return {"success": False, "error": "Job not found or already finished"}
    pinfo["cancel"] = True
    proc = pinfo.get("current_proc")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
    logging.info(f"[VOD] Stop requested for {job_id}")
    return {"success": True, "message": "Stop requested"}


def get_vod_job_status(job_id: str) -> dict:
    pinfo = _vod_jobs.get(job_id)
    if not pinfo:
        return {"job_id": job_id, "status": "NOT_FOUND"}
    status = pinfo.get("status", "RUNNING")
    return {
        "job_id": job_id,
        "status": status,
        "started_at": pinfo.get("started_at"),
        "pid": pinfo["current_proc"].pid if pinfo.get("current_proc") else None,
        "progress_pct": 100 if status == "COMPLETED" else pinfo.get("progress_pct", 0),
    }


def list_active_vod_jobs() -> list:
    return [
        {"job_id": jid, "status": info.get("status", "RUNNING"),
         "name": info["job_config"].get("name", jid),
         "started_at": info.get("started_at")}
        for jid, info in _vod_jobs.items()
    ]


def get_vod_job_logs(job_id: str, tail: int = 100) -> str:
    pinfo = _vod_jobs.get(job_id)
    log_path = pinfo.get("log_path") if pinfo else os.path.join(_LOGS_DIR, f"vod_{job_id}.log")
    if not log_path or not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-tail:])
    except Exception:
        return ""

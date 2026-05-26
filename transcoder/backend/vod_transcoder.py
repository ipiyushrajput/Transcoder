import os
import re
import uuid
import shutil
import logging
import tempfile
import subprocess
import threading
import fractions
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from esam_processor import parse_esam_scc_xml, process_esam_on_output, parse_variant_segments
from s3_uploader import build_s3_client, start_live_upload_watcher, upload_directory_to_s3
from subtitle_processor import convert_subtitle_to_vtt, segment_vtt_for_hls

# In-memory process registry
_vod_processes = {}
_vod_locks = {}
_executor = ThreadPoolExecutor(max_workers=10)


def _get_fps(input_url: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", input_url],
            capture_output=True, text=True, timeout=15,
        )
        fps_str = result.stdout.strip()
        if fps_str:
            return float(fractions.Fraction(fps_str))
    except Exception:
        pass
    return 25.0


def _get_input_duration(input_url: str) -> float:
    """Return duration of input in seconds using ffprobe. Returns 0.0 on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_url],
            capture_output=True, text=True, timeout=20,
        )
        val = result.stdout.strip()
        if val:
            return float(val)
    except Exception:
        pass
    return 0.0


def _parse_ffmpeg_progress(log_path: str, total_duration: float) -> int:
    """Parse FFmpeg log for the latest 'time=HH:MM:SS.FF'. Returns 0-99 percent."""
    if not total_duration or total_duration <= 0:
        return 0
    try:
        with open(log_path, "r", errors="replace") as f:
            content = f.read()
        matches = re.findall(r"time=(\d+:\d+:\d+\.\d+)", content)
        if not matches:
            return 0
        parts = matches[-1].split(":")
        elapsed = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        pct = int(elapsed / total_duration * 100)
        return max(0, min(pct, 99))
    except Exception:
        return 0


def _timecode_to_seconds(tc: str, fps: float) -> float:
    parts = tc.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timecode: {tc}")
    hh, mm, ss, ff = map(int, parts)
    return round(hh * 3600 + mm * 60 + ss + ff / fps, 5)


def _build_input_clipping_ffconcat(input_url: str, clips: list, fps: float, tmp_dir: str):
    """Create ffconcat file for input clipping."""
    lines = ["ffconcat version 1.0"]
    abs_input = os.path.abspath(input_url) if not input_url.startswith(("http", "rtmp", "s3")) else input_url
    for clip in clips:
        start = _timecode_to_seconds(clip["start_timecode"], fps)
        end = _timecode_to_seconds(clip["end_timecode"], fps)
        if end <= start:
            continue
        lines.append(f"\nfile '{abs_input}'")
        lines.append(f"inpoint {start}")
        lines.append(f"outpoint {end}")

    concat_path = os.path.join(tmp_dir, "input.ffconcat")
    with open(concat_path, "w") as f:
        f.write("\n".join(lines))
    return concat_path


def _compute_clip_boundaries(clips: list, fps: float) -> tuple:
    """
    Compute (clip_boundary_times, total_output_duration) for force_key_frames.
    Boundaries are the transition points in the output timeline (excluding 0).
    """
    boundary_times = []
    cumulative = 0.0
    for clip in clips:
        start = _timecode_to_seconds(clip["start_timecode"], fps)
        end = _timecode_to_seconds(clip["end_timecode"], fps)
        dur = max(0.0, end - start)
        cumulative += dur
        boundary_times.append(round(cumulative, 3))
    # Last boundary is the total duration, not a transition; drop it
    if boundary_times:
        total = boundary_times.pop()
    else:
        total = 0.0
    return boundary_times, total


def _update_master_for_subtitles(master_path: str, lang: str = "en"):
    """Add subtitle EXT-X-MEDIA tag and SUBTITLES attribute to master playlist."""
    if not os.path.exists(master_path):
        return

    sub_playlist = f"sub_{lang}.m3u8"
    with open(master_path, "r") as f:
        lines = f.readlines()

    has_sub_attr = any('SUBTITLES="subs"' in l for l in lines)
    new_lines = [
        "#EXTM3U\n",
        "#EXT-X-VERSION:3\n",
        "#EXT-X-INDEPENDENT-SEGMENTS\n",
    ]
    for line in lines:
        stripped = line.strip()
        if stripped in ("#EXTM3U",) or stripped.startswith("#EXT-X-VERSION:") or stripped == "#EXT-X-INDEPENDENT-SEGMENTS":
            continue
        if line.startswith("#EXT-X-STREAM-INF") and not has_sub_attr:
            new_lines.append(line.rstrip() + ',SUBTITLES="subs"\n')
        elif "TYPE=SUBTITLES" in line:
            continue
        else:
            new_lines.append(line)

    sub_tag = (
        f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",'
        f'DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,LANGUAGE="{lang}",URI="{sub_playlist}"\n'
    )
    new_lines.append(sub_tag)

    with open(master_path, "w") as f:
        f.writelines(new_lines)


def build_vod_ffmpeg_command(
    input_path: str,
    output_dir: str,
    variants: list,
    segment_size: int,
    master_filename: str,
    preset: str = "medium",
    hls_playlist_type: str = "vod",
    hls_flags: str = "independent_segments",
    hls_list_size: int = 0,
    ffmpeg_path: str = "ffmpeg",
    use_concat: bool = False,
    deinterlace: bool = True,
    clip_boundary_times: list = None,
    total_output_duration: float = 0.0,
) -> List[str]:
    """Build FFmpeg command for multi-bitrate HLS output."""
    num = len(variants)
    split_labels = [f"[v{i}]" for i in range(num)]

    filter_parts = [f"[0:v]split={num}{''.join(split_labels)}"]
    for i, v in enumerate(variants):
        w, h = v["width"], v["height"]
        deint_filter = "yadif=mode=0:parity=auto:deint=1," if deinterlace else ""
        scale_filter = (
            f"{deint_filter}scale=w={w}:h={h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )
        filter_parts.append(f"[v{i}]{scale_filter}[v{i}out]")

    if use_concat:
        filter_parts.append(f"[0:a]aresample=async=1000[a_resampled]")
        filter_parts.append(f"[a_resampled]asplit={num}{''.join(f'[a{i}out]' for i in range(num))}")
    else:
        filter_parts.append(f"[0:a]asplit={num}{''.join(f'[a{i}out]' for i in range(num))}")

    filter_complex = "; ".join(filter_parts)

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-thread_queue_size", "1024"]

    if use_concat:
        cmd.extend(["-safe", "0"])
        cmd.extend(["-protocol_whitelist", "file,http,https,tcp,tls,crypto"])
        cmd.extend(["-fflags", "+genpts"])

    cmd.extend(["-i", input_path])
    cmd.extend(["-filter_complex", filter_complex])

    # Build force_key_frames expression
    # For clipped content, use an explicit keyframe list to get short EXTINF at boundaries
    if clip_boundary_times:
        kf_times = set()
        # Regular interval keyframes (cover full output duration + a buffer)
        max_t = (total_output_duration if total_output_duration > 0 else 7200) + segment_size * 2
        t = 0.0
        while t <= max_t:
            kf_times.add(round(t, 3))
            t += segment_size
        kf_times.update(clip_boundary_times)
        kf_str = ",".join(str(k) for k in sorted(kf_times))
        force_kf_expr = kf_str
    else:
        force_kf_expr = f"expr:gte(t,n_forced*{segment_size})"

    for i, v in enumerate(variants):
        codec = v.get("video_codec", "libx264")
        bitrate = v.get("video_bitrate", 2000000)
        framerate = v.get("framerate", "25")
        ref = int(v.get("reference_frames", 4))
        profile = v.get("profile", "main")
        level = v.get("level", "4.1")
        audio_codec = v.get("audio_codec", "aac")
        audio_bitrate = v.get("audio_bitrate", 128000)
        sample_rate = v.get("sample_rate", 48000)

        cmd.extend(["-map", f"[v{i}out]", "-map", f"[a{i}out]"])
        cmd.extend([f"-c:v:{i}", codec])

        if codec == "libx264":
            x264_params = (
                f"rc-lookahead=32:bframes=3:ref={ref}:nal-hrd=cbr:"
                f"bitrate={bitrate // 1000}:vbv-maxrate={bitrate // 1000}:vbv-bufsize={bitrate // 500}"
            )
            cmd.extend([
                f"-x264-params:v:{i}", x264_params,
                f"-profile:v:{i}", profile,
                f"-level:v:{i}", level,
            ])
        elif codec == "libx265":
            x265_params = (
                f"rc-lookahead=32:bframes=3:ref={ref}:"
                f"vbv-maxrate={bitrate // 1000}:vbv-bufsize={bitrate // 500}"
            )
            cmd.extend([
                f"-x265-params:v:{i}", x265_params,
                f"-tag:v:{i}", "hvc1",
            ])

        cmd.extend([
            f"-b:v:{i}", str(bitrate),
            f"-r:v:{i}", str(framerate),
            f"-preset:v:{i}", preset,
            f"-force_key_frames:v:{i}", force_kf_expr,
            f"-pix_fmt:v:{i}", "yuv420p",
        ])
        cmd.extend([
            f"-c:a:{i}", audio_codec,
            f"-b:a:{i}", str(audio_bitrate),
            f"-ar:a:{i}", str(sample_rate),
        ])

    stream_map_entries = [
        f"v:{i},a:{i},name:{v.get('height', 'v' + str(i))}p"
        for i, v in enumerate(variants)
    ]
    cmd.extend(["-var_stream_map", " ".join(stream_map_entries)])

    segment_filename = os.path.join(output_dir, "segment_%v_%05d.ts")
    variant_playlist = os.path.join(output_dir, "variant_%v.m3u8")

    cmd.extend([
        "-f", "hls",
        "-start_number", "1",
        "-hls_time", str(segment_size),
        "-hls_segment_filename", segment_filename,
        "-master_pl_name", f"{master_filename}.m3u8",
        "-hls_segment_type", "mpegts",
    ])

    if hls_playlist_type:
        cmd.extend(["-hls_playlist_type", hls_playlist_type])
    if hls_flags:
        cmd.extend(["-hls_flags", hls_flags])
    if hls_list_size is not None:
        cmd.extend(["-hls_list_size", str(hls_list_size)])

    cmd.append(variant_playlist)
    return cmd


def build_mp4_output_command(
    input_path: str,
    output_file: str,
    variants: list,
    preset: str = "medium",
    ffmpeg_path: str = "ffmpeg",
    use_concat: bool = False,
) -> List[str]:
    """Build FFmpeg command for single MP4 output (highest quality variant)."""
    v = variants[0]
    cmd = [ffmpeg_path, "-y", "-hide_banner", "-thread_queue_size", "1024"]
    if use_concat:
        cmd.extend(["-safe", "0"])
    cmd.extend(["-i", input_path])
    cmd.extend([
        "-c:v", v.get("video_codec", "libx264"),
        "-b:v", str(v.get("video_bitrate", 4000000)),
        "-r", str(v.get("framerate", "25")),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        "-c:a", v.get("audio_codec", "aac"),
        "-b:a", str(v.get("audio_bitrate", 128000)),
        "-ar", str(v.get("sample_rate", 48000)),
        output_file,
    ])
    return cmd


def start_vod_job(job_config: dict, db_update_callback=None) -> dict:
    """
    Start a VOD transcoding job. Returns dict with job_id and status.
    """
    job_id = job_config.get("job_id") or str(uuid.uuid4())
    name = job_config.get("name", job_id)
    ffmpeg_path = "ffmpeg"

    logging.info(f"[VOD:{name}] Starting job {job_id}")

    tmp_dir = tempfile.mkdtemp(prefix=f"vod_{job_id[:8]}_")

    dest = job_config.get("output_destination", "LOCAL").upper()
    _local_path = job_config.get("local_path", "").strip()
    if dest == "LOCAL" and _local_path:
        output_dir = _local_path
    else:
        output_dir = os.path.join(tmp_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    input_url = job_config["input_url"]
    clips = job_config.get("clips", [])
    use_concat = False
    clip_boundary_times = []
    total_output_duration = 0.0

    # Get input duration for progress tracking
    input_duration = _get_input_duration(input_url)

    if clips:
        fps = _get_fps(input_url)
        try:
            ffconcat_path = _build_input_clipping_ffconcat(input_url, clips, fps, tmp_dir)
            input_url = ffconcat_path
            use_concat = True
            logging.info(f"[VOD:{name}] Using ffconcat for {len(clips)} clip(s)")
            clip_boundary_times, total_output_duration = _compute_clip_boundaries(clips, fps)
            logging.info(f"[VOD:{name}] Clip boundaries at: {clip_boundary_times}, total={total_output_duration:.3f}s")
        except Exception as e:
            logging.error(f"[VOD:{name}] Clip processing failed: {e}")
            return {"success": False, "error": str(e)}
    else:
        total_output_duration = input_duration

    variants = job_config.get("variants", [])
    if not variants:
        return {"success": False, "error": "No output variants specified"}

    output_type = job_config.get("output_type", "HLS").upper()
    segment_size = int(job_config.get("segment_length", 6))
    master_filename = job_config.get("master_filename", "master")
    preset = job_config.get("preset", "medium")

    # Pre-encode subtitle conversion (just format conversion, not segmentation)
    sub_url = job_config.get("subtitle_url")
    sub_lang = job_config.get("subtitle_language", "en")
    sub_vtt_path = None
    if sub_url and output_type == "HLS":
        sub_vtt_path = os.path.join(tmp_dir, f"subtitle_{sub_lang}.vtt")
        if not convert_subtitle_to_vtt(ffmpeg_path, sub_url, sub_vtt_path):
            sub_vtt_path = None
            logging.warning(f"[VOD:{name}] Subtitle conversion failed, proceeding without subtitles")

    if output_type == "HLS":
        ffmpeg_cmd = build_vod_ffmpeg_command(
            input_path=input_url,
            output_dir=output_dir,
            variants=variants,
            segment_size=segment_size,
            master_filename=master_filename,
            preset=preset,
            hls_playlist_type=job_config.get("hls_playlist_type", "vod"),
            hls_flags=job_config.get("hls_flags", "independent_segments"),
            hls_list_size=job_config.get("hls_list_size", 0),
            ffmpeg_path=ffmpeg_path,
            use_concat=use_concat,
            clip_boundary_times=clip_boundary_times,
            total_output_duration=total_output_duration,
        )
    else:
        output_file = os.path.join(output_dir, f"{master_filename}.mp4")
        ffmpeg_cmd = build_mp4_output_command(
            input_path=input_url,
            output_file=output_file,
            variants=variants,
            preset=preset,
            ffmpeg_path=ffmpeg_path,
            use_concat=use_concat,
        )

    log_path = os.path.join(tmp_dir, "ffmpeg.log")
    logging.info(f"[VOD:{name}] FFmpeg cmd: {' '.join(ffmpeg_cmd)}")

    observer = handler = periodic = None
    s3_client = None
    if dest == "S3":
        bucket = job_config.get("s3_bucket", "")
        s3_prefix = job_config.get("s3_path", name).strip("/")
        try:
            s3_client = build_s3_client()
            observer, handler, periodic = start_live_upload_watcher(output_dir, bucket, s3_prefix, s3_client)
        except Exception as e:
            logging.error(f"[VOD:{name}] S3 watcher failed: {e}")

    with open(log_path, "w") as log_f:
        process = subprocess.Popen(ffmpeg_cmd, stdout=log_f, stderr=log_f)

    lock = threading.Lock()
    _vod_locks[job_id] = lock
    _vod_processes[job_id] = {
        "process": process,
        "tmp_dir": tmp_dir,
        "output_dir": output_dir,
        "log_path": log_path,
        "job_config": job_config,
        "observer": observer,
        "handler": handler,
        "periodic": periodic,
        "s3_client": s3_client,
        "started_at": datetime.utcnow().isoformat(),
        "status": "RUNNING",
        "sub_vtt_path": sub_vtt_path,
        "sub_lang": sub_lang,
        "master_filename": master_filename,
        "output_type": output_type,
        "total_output_duration": total_output_duration,
        "ffmpeg_path": ffmpeg_path,
    }

    if db_update_callback:
        db_update_callback(job_id, "RUNNING", process.pid)

    _executor.submit(_monitor_vod_process, job_id, db_update_callback)

    playback_url = _build_playback_url(job_config)
    return {
        "success": True,
        "job_id": job_id,
        "status": "RUNNING",
        "playback_url": playback_url,
        "pid": process.pid,
    }


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
    else:
        local = job_config.get("local_path", "/tmp/output")
        return f"file://{local}/{master}.m3u8"


def _monitor_vod_process(job_id: str, db_update_callback=None):
    """Monitor VOD FFmpeg process and handle post-encode tasks."""
    pinfo = _vod_processes.get(job_id)
    if not pinfo:
        return

    process = pinfo["process"]
    name = pinfo["job_config"].get("name", job_id)

    try:
        process.wait()
    except Exception as e:
        logging.error(f"[VOD:{name}] Process wait error: {e}")
        return

    if job_id not in _vod_processes:
        return  # Stopped manually

    returncode = process.returncode
    lock = _vod_locks.get(job_id)
    if not lock:
        return

    with lock:
        if job_id not in _vod_processes:
            return

        pinfo = _vod_processes[job_id]
        output_dir = pinfo["output_dir"]
        job_config = pinfo["job_config"]
        master_filename = pinfo["master_filename"]
        output_type = pinfo["output_type"]
        sub_vtt_path = pinfo.get("sub_vtt_path")
        sub_lang = pinfo.get("sub_lang", "en")
        ffmpeg_path = pinfo.get("ffmpeg_path", "ffmpeg")

        _stop_watchers(pinfo)

        if returncode == 0:
            logging.info(f"[VOD:{name}] FFmpeg completed successfully")
            status = "COMPLETED"
            sub_playlist = None

            # Post-encode subtitle segmentation aligned to video segments
            if sub_vtt_path and output_type == "HLS":
                vtt_path = Path(sub_vtt_path)
                if vtt_path.exists():
                    variant_files = sorted(Path(output_dir).glob("variant_*.m3u8"))
                    if variant_files:
                        try:
                            _, v_segments, _ = parse_variant_segments(variant_files[0])
                            if v_segments:
                                sub_playlist = segment_vtt_for_hls(vtt_path, v_segments, output_dir, sub_lang)
                                logging.info(f"[VOD:{name}] Subtitle segmented: {sub_playlist}")
                        except Exception as e:
                            logging.error(f"[VOD:{name}] Subtitle segmentation failed: {e}")

            if sub_playlist and output_type == "HLS":
                master_path = os.path.join(output_dir, f"{master_filename}.m3u8")
                _update_master_for_subtitles(master_path, sub_lang)

            # ESAM injection
            if job_config.get("esam_enabled") and job_config.get("esam_scc_xml"):
                events = parse_esam_scc_xml(job_config["esam_scc_xml"])
                mcc_xml = job_config.get("esam_mcc_xml")
                if events and output_type == "HLS":
                    cnt = process_esam_on_output(output_dir, events, sub_playlist, mcc_xml=mcc_xml)
                    logging.info(f"[VOD:{name}] Injected {cnt} ESAM markers")

            # Upload to S3
            dest = job_config.get("output_destination", "LOCAL").upper()
            if dest == "S3":
                bucket = job_config.get("s3_bucket", "")
                s3_prefix = job_config.get("s3_path", name).strip("/")
                try:
                    s3_client = pinfo.get("s3_client") or build_s3_client()
                    cnt = upload_directory_to_s3(output_dir, bucket, s3_prefix, s3_client)
                    logging.info(f"[VOD:{name}] Final S3 upload: {cnt} files")
                except Exception as e:
                    logging.error(f"[VOD:{name}] Final S3 upload error: {e}")
            elif dest == "LOCAL":
                local_path = job_config.get("local_path", "")
                if local_path:
                    logging.info(f"[VOD:{name}] Output at {local_path}")
        else:
            logging.error(f"[VOD:{name}] FFmpeg failed (rc={returncode})")
            status = "FAILED"
            error_msg = ""
            try:
                with open(pinfo["log_path"], "r") as f:
                    error_msg = f.read()[-3000:]
            except Exception:
                pass
            pinfo["error_message"] = error_msg

        pinfo["status"] = status
        pinfo["completed_at"] = datetime.utcnow().isoformat()

        error_to_save = pinfo.get("error_message") if status == "FAILED" else None
        if db_update_callback:
            db_update_callback(job_id, status, None, error_to_save)

        try:
            shutil.rmtree(pinfo["tmp_dir"], ignore_errors=True)
        except Exception:
            pass

        _vod_processes.pop(job_id, None)
        _vod_locks.pop(job_id, None)


def _stop_watchers(pinfo: dict):
    try:
        if pinfo.get("periodic"):
            pinfo["periodic"].stop()
        if pinfo.get("handler"):
            pinfo["handler"].stop()
        if pinfo.get("observer") and pinfo["observer"].is_alive():
            pinfo["observer"].stop()
            pinfo["observer"].join(timeout=5)
    except Exception as e:
        logging.warning(f"Error stopping watchers: {e}")


def stop_vod_job(job_id: str, db_update_callback=None) -> dict:
    """Stop a running VOD job."""
    lock = _vod_locks.get(job_id)
    if not lock:
        return {"success": False, "error": "Job not found or already stopped"}

    with lock:
        pinfo = _vod_processes.get(job_id)
        if not pinfo:
            return {"success": False, "error": "Job not found"}

        process = pinfo["process"]
        name = pinfo["job_config"].get("name", job_id)
        _stop_watchers(pinfo)

        try:
            process.terminate()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        except Exception as e:
            logging.error(f"[VOD:{name}] Stop error: {e}")

        pinfo["status"] = "STOPPED"

        try:
            shutil.rmtree(pinfo["tmp_dir"], ignore_errors=True)
        except Exception:
            pass

        _vod_processes.pop(job_id, None)
        _vod_locks.pop(job_id, None)

        if db_update_callback:
            db_update_callback(job_id, "STOPPED", None)

        logging.info(f"[VOD:{name}] Job {job_id} stopped")
        return {"success": True, "message": "Job stopped"}


def get_vod_job_status(job_id: str) -> dict:
    """Get current status and progress of a VOD job."""
    pinfo = _vod_processes.get(job_id)
    if not pinfo:
        return {"job_id": job_id, "status": "NOT_FOUND"}

    process = pinfo["process"]
    returncode = process.poll()
    status = pinfo.get("status", "RUNNING")
    if returncode is not None and status == "RUNNING":
        status = "COMPLETED" if returncode == 0 else "FAILED"

    progress_pct = 0
    if status == "RUNNING":
        log_path = pinfo.get("log_path", "")
        total_dur = pinfo.get("total_output_duration", 0.0)
        if log_path and os.path.exists(log_path) and total_dur > 0:
            progress_pct = _parse_ffmpeg_progress(log_path, total_dur)
    elif status == "COMPLETED":
        progress_pct = 100

    return {
        "job_id": job_id,
        "status": status,
        "started_at": pinfo.get("started_at"),
        "pid": process.pid if process else None,
        "progress_pct": progress_pct,
    }


def list_active_vod_jobs() -> list:
    return [
        {"job_id": jid, "status": info.get("status", "RUNNING"),
         "name": info["job_config"].get("name", jid),
         "started_at": info.get("started_at")}
        for jid, info in _vod_processes.items()
    ]


def get_vod_job_logs(job_id: str, tail: int = 100) -> str:
    """Get last N lines of FFmpeg log for a job."""
    pinfo = _vod_processes.get(job_id)
    if not pinfo:
        return ""
    log_path = pinfo.get("log_path", "")
    if not log_path or not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "r") as f:
            lines = f.readlines()
        return "".join(lines[-tail:])
    except Exception:
        return ""

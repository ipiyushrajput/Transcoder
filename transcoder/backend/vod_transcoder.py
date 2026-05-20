import os
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

from esam_processor import parse_esam_scc_xml, process_esam_on_output
from s3_uploader import build_s3_client, start_live_upload_watcher, upload_directory_to_s3

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


def _process_subtitles(ffmpeg_path: str, subtitle_url: str, output_dir: str, lang: str = "en") -> Optional[str]:
    """Generate HLS subtitle playlist from subtitle file. Returns playlist path or None."""
    if not subtitle_url:
        return None

    playlist_name = f"sub_{lang}.m3u8"
    segment_pattern = f"sub_{lang}_%05d.vtt"
    playlist_path = os.path.join(output_dir, playlist_name)
    segment_path = os.path.join(output_dir, segment_pattern)

    cmd = [
        ffmpeg_path, "-y",
        "-i", subtitle_url,
        "-map", "0:0",
        "-c:s", "webvtt",
        "-f", "segment",
        "-segment_time", "6",
        "-segment_list_type", "m3u8",
        "-hls_playlist_type", "vod",
        "-segment_list", playlist_path,
        "-segment_format", "webvtt",
        segment_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        logging.info(f"Subtitle HLS generated: {playlist_path}")
        return playlist_path
    except Exception as e:
        logging.error(f"Subtitle processing failed: {e}")
        return None


def _update_master_for_subtitles(master_path: str, lang: str = "en"):
    """Add subtitle EXT-X-MEDIA tag and SUBTITLES attribute to master playlist."""
    if not os.path.exists(master_path):
        return

    sub_playlist = f"sub_{lang}.m3u8"
    with open(master_path, "r") as f:
        lines = f.readlines()

    has_sub_media = any("#EXT-X-MEDIA:TYPE=SUBTITLES" in l for l in lines)
    has_sub_attr = any('SUBTITLES="subs"' in l for l in lines)

    new_lines = []
    has_version = any("#EXT-X-VERSION" in l for l in lines)
    has_extm3u = any("#EXTM3U" in l.strip() for l in lines)

    new_lines.append("#EXTM3U\n")
    new_lines.append("#EXT-X-VERSION:3\n")
    new_lines.append("#EXT-X-INDEPENDENT-SEGMENTS\n")

    for line in lines:
        stripped = line.strip()
        if stripped == "#EXTM3U" or stripped.startswith("#EXT-X-VERSION:") or stripped == "#EXT-X-INDEPENDENT-SEGMENTS":
            continue
        if line.startswith("#EXT-X-STREAM-INF") and not has_sub_attr:
            new_lines.append(line.rstrip() + ',SUBTITLES="subs"\n')
        elif line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"):
            continue
        else:
            new_lines.append(line)

    if not has_sub_media:
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
) -> List[str]:
    """
    Build ffmpeg command for multi-bitrate HLS output.
    Codec settings based on existing s3_transcoder.py and ffmpeg.py patterns.
    """
    num = len(variants)
    split_labels = [f"[v{i}]" for i in range(num)]

    # filter_complex: split video + scale each variant + split audio
    filter_parts = [f"[0:v]split={num}{''.join(split_labels)}"]
    for i, v in enumerate(variants):
        w, h = v["width"], v["height"]
        scale_filter = f"scale=w={w}:h={h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        filter_parts.append(f"[v{i}]{scale_filter}[v{i}out]")
    filter_parts.append(
        f"[0:a]asplit={num}{''.join(f'[a{i}out]' for i in range(num))}"
    )
    filter_complex = "; ".join(filter_parts)

    cmd = [ffmpeg_path, "-y", "-hide_banner"]

    if use_concat:
        cmd.extend(["-safe", "0"])
    cmd.extend(["-i", input_path])
    cmd.extend(["-filter_complex", filter_complex])

    for i, v in enumerate(variants):
        codec = v.get("video_codec", "libx264")
        bitrate = v.get("video_bitrate", 2000000)
        framerate = v.get("framerate", "25")
        gop = int(v.get("gop", 60))
        ref = int(v.get("reference_frames", 4))
        profile = v.get("profile", "main")
        level = v.get("level", "4.1")
        audio_codec = v.get("audio_codec", "aac")
        audio_bitrate = v.get("audio_bitrate", 128000)
        sample_rate = v.get("sample_rate", 48000)

        cmd.extend(["-map", f"[v{i}out]", "-map", f"[a{i}out]"])

        # Video codec settings
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
            f"-force_key_frames:v:{i}", f"expr:gte(t,n_forced*{segment_size})",
            f"-pix_fmt:v:{i}", "yuv420p",
        ])

        # Audio settings
        cmd.extend([
            f"-c:a:{i}", audio_codec,
            f"-b:a:{i}", str(audio_bitrate),
            f"-ar:v:{i}", str(sample_rate),
        ])

    # var_stream_map
    stream_map_entries = [
        f"v:{i},a:{i},name:{v.get('height', 'v' + str(i))}p"
        for i, v in enumerate(variants)
    ]
    cmd.extend(["-var_stream_map", " ".join(stream_map_entries)])

    # HLS output settings
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
    """Build ffmpeg command for single MP4 output (highest quality variant)."""
    v = variants[0]  # Use first/highest variant for MP4 output
    cmd = [ffmpeg_path, "-y", "-hide_banner"]
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
    job_config keys:
        job_id, name, input_url, input_type, clips, subtitle_url, subtitle_language,
        output_type (HLS/MP4), output_destination (S3/LOCAL),
        s3_bucket, s3_path, s3_cloudfront_domain, local_path,
        master_filename, segment_length, hls_playlist_type, hls_flags, hls_list_size,
        preset, variants, esam_enabled, esam_scc_xml
    """
    job_id = job_config.get("job_id") or str(uuid.uuid4())
    name = job_config.get("name", job_id)
    ffmpeg_path = "ffmpeg"

    logging.info(f"[VOD:{name}] Starting job {job_id}")

    # Create temp working dir
    tmp_dir = tempfile.mkdtemp(prefix=f"vod_{job_id[:8]}_")
    output_dir = os.path.join(tmp_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    input_url = job_config["input_url"]
    clips = job_config.get("clips", [])
    use_concat = False

    # Handle input clipping
    if clips:
        fps = _get_fps(input_url)
        try:
            ffconcat_path = _build_input_clipping_ffconcat(input_url, clips, fps, tmp_dir)
            input_url = ffconcat_path
            use_concat = True
            logging.info(f"[VOD:{name}] Using ffconcat for {len(clips)} clip(s)")
        except Exception as e:
            logging.error(f"[VOD:{name}] Clip processing failed: {e}")
            return {"success": False, "error": str(e)}

    # Process subtitles
    sub_url = job_config.get("subtitle_url")
    sub_lang = job_config.get("subtitle_language", "en")
    sub_playlist = None
    if sub_url:
        sub_playlist = _process_subtitles(ffmpeg_path, sub_url, output_dir, sub_lang)

    variants = job_config.get("variants", [])
    if not variants:
        return {"success": False, "error": "No output variants specified"}

    output_type = job_config.get("output_type", "HLS").upper()
    segment_size = int(job_config.get("segment_length", 6))
    master_filename = job_config.get("master_filename", "master")
    preset = job_config.get("preset", "medium")

    # Build FFmpeg command
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

    # Start S3 watcher if destination is S3
    observer = handler = periodic = None
    dest = job_config.get("output_destination", "LOCAL").upper()
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
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=log_f,
            stderr=log_f,
        )

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
        "sub_playlist": sub_playlist,
        "sub_lang": sub_lang,
        "master_filename": master_filename,
        "output_type": output_type,
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
        region = "us-east-1"
        return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_path}/{master}.m3u8"
    elif dest == "MEDIAPACKAGE":
        return job_config.get("mediapackage_url", "")
    else:
        local = job_config.get("local_path", "/tmp/output")
        return f"file://{local}/{master}.m3u8"


def _monitor_vod_process(job_id: str, db_update_callback=None):
    """Monitor VOD ffmpeg process completion and trigger post-processing."""
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
        sub_playlist = pinfo.get("sub_playlist")
        sub_lang = pinfo.get("sub_lang", "en")

        # Stop S3 watchers
        _stop_watchers(pinfo)

        if returncode == 0:
            logging.info(f"[VOD:{name}] FFmpeg completed successfully")
            status = "COMPLETED"

            # Post-processing: update master playlist with subtitle refs
            if sub_playlist and output_type == "HLS":
                master_path = os.path.join(output_dir, f"{master_filename}.m3u8")
                _update_master_for_subtitles(master_path, sub_lang)

            # Post-processing: ESAM injection
            if job_config.get("esam_enabled") and job_config.get("esam_scc_xml"):
                events = parse_esam_scc_xml(job_config["esam_scc_xml"])
                if events and output_type == "HLS":
                    cnt = process_esam_on_output(output_dir, events)
                    logging.info(f"[VOD:{name}] Injected {cnt} ESAM markers")

            # Final S3 upload (batch)
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
                    try:
                        os.makedirs(local_path, exist_ok=True)
                        for item in os.listdir(output_dir):
                            src = os.path.join(output_dir, item)
                            dst = os.path.join(local_path, item)
                            if os.path.isfile(src):
                                shutil.copy2(src, dst)
                        logging.info(f"[VOD:{name}] Files copied to {local_path}")
                    except Exception as e:
                        logging.error(f"[VOD:{name}] Local copy error: {e}")
        else:
            logging.error(f"[VOD:{name}] FFmpeg failed (rc={returncode})")
            status = "FAILED"

            # Read error from log
            error_msg = ""
            try:
                with open(pinfo["log_path"], "r") as f:
                    error_msg = f.read()[-2000:]
            except Exception:
                pass
            pinfo["error_message"] = error_msg

        pinfo["status"] = status
        pinfo["completed_at"] = datetime.utcnow().isoformat()

        if db_update_callback:
            db_update_callback(job_id, status, None)

        # Cleanup temp dir
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
    """Get current status of a VOD job."""
    pinfo = _vod_processes.get(job_id)
    if not pinfo:
        return {"job_id": job_id, "status": "NOT_FOUND"}

    process = pinfo["process"]
    returncode = process.poll()

    status = pinfo.get("status", "RUNNING")
    if returncode is not None and status == "RUNNING":
        status = "COMPLETED" if returncode == 0 else "FAILED"

    return {
        "job_id": job_id,
        "status": status,
        "started_at": pinfo.get("started_at"),
        "pid": process.pid if process else None,
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

import os
import uuid
import shutil
import logging
import tempfile
import subprocess
import threading
from datetime import datetime
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from s3_uploader import build_s3_client, start_live_upload_watcher

_live_channels = {}
_live_locks = {}
_executor = ThreadPoolExecutor(max_workers=10)

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR = os.path.join(_BACKEND_DIR, "logs")
os.makedirs(_LOGS_DIR, exist_ok=True)


def build_live_hls_command(
    input_url: str,
    output_dir: str,
    variants: list,
    segment_size: int,
    master_filename: str,
    preset: str = "ultrafast",
    hls_list_size: int = 6,
    hls_flags: str = "delete_segments+append_list",
    ffmpeg_path: str = "ffmpeg",
    input_type: str = "HLS",
) -> List[str]:
    """Build FFmpeg command for live HLS output."""
    num = len(variants)

    filter_parts = [f"[0:v]split={num}{''.join(f'[v{i}]' for i in range(num))}"]
    for i, v in enumerate(variants):
        w, h = v["width"], v["height"]
        filter_parts.append(
            f"[v{i}]scale=w={w}:h={h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v{i}out]"
        )
    filter_parts.append(
        f"[0:a]asplit={num}{''.join(f'[a{i}out]' for i in range(num))}"
    )
    filter_complex = "; ".join(filter_parts)

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "warning"]

    # Input-specific flags
    if input_type in ("RTMP", "SRT"):
        cmd.extend(["-re"])
    elif input_type in ("HLS", "HTTP"):
        cmd.extend(["-re"])

    # For RTMP/SRT, avoid reconnect issues
    if input_type == "SRT":
        cmd.extend(["-fflags", "+genpts"])

    cmd.extend(["-i", input_url])
    cmd.extend(["-filter_complex", filter_complex])

    for i, v in enumerate(variants):
        codec = v.get("video_codec", "libx264")
        bitrate = v.get("video_bitrate", 2000000)
        framerate = v.get("framerate", "25")
        gop = int(v.get("gop", 60))
        ref = int(v.get("reference_frames", 2))
        profile = v.get("profile", "main")
        level = v.get("level", "4.1")
        audio_codec = v.get("audio_codec", "aac")
        audio_bitrate = v.get("audio_bitrate", 128000)
        sample_rate = v.get("sample_rate", 48000)

        cmd.extend(["-map", f"[v{i}out]", "-map", f"[a{i}out]"])
        cmd.extend([f"-c:v:{i}", codec])

        if codec == "libx264":
            x264_params = (
                f"rc-lookahead=16:bframes=2:ref={ref}:nal-hrd=cbr:"
                f"bitrate={bitrate // 1000}:vbv-maxrate={bitrate // 1000}:"
                f"vbv-bufsize={bitrate // 500}"
            )
            cmd.extend([
                f"-x264-params:v:{i}", x264_params,
                f"-profile:v:{i}", profile,
                f"-level:v:{i}", level,
            ])
        elif codec == "libx265":
            x265_params = (
                f"rc-lookahead=16:bframes=2:ref={ref}:"
                f"vbv-maxrate={bitrate // 1000}:vbv-bufsize={bitrate // 500}"
            )
            cmd.extend([
                f"-x265-params:v:{i}", x265_params,
                f"-tag:v:{i}", "hvc1",
            ])

        cmd.extend([
            f"-b:v:{i}", str(bitrate),
            f"-r:v:{i}", str(framerate),
            f"-g:v:{i}", str(gop),
            f"-preset:v:{i}", preset,
            f"-pix_fmt:v:{i}", "yuv420p",
            f"-c:a:{i}", audio_codec,
            f"-b:a:{i}", str(audio_bitrate),
            f"-ar:a:{i}", str(sample_rate),
        ])

    stream_map = " ".join(
        f"v:{i},a:{i},name:{v.get('height', str(i))}p"
        for i, v in enumerate(variants)
    )
    cmd.extend(["-var_stream_map", stream_map])

    segment_filename = os.path.join(output_dir, "seg_%v_%05d.ts")
    variant_playlist = os.path.join(output_dir, "live_%v.m3u8")

    cmd.extend([
        "-f", "hls",
        "-start_number", "1",
        "-hls_time", str(segment_size),
        "-hls_list_size", str(hls_list_size),
        "-hls_segment_filename", segment_filename,
        "-master_pl_name", f"{master_filename}.m3u8",
        "-hls_flags", hls_flags,
        "-hls_segment_type", "mpegts",
        variant_playlist,
    ])

    return cmd


def build_live_rtmp_passthrough_command(
    input_url: str,
    rtmp_output_url: str,
    ffmpeg_path: str = "ffmpeg",
) -> List[str]:
    """Simple RTMP passthrough / re-stream command."""
    return [
        ffmpeg_path, "-y", "-hide_banner", "-re",
        "-i", input_url,
        "-c", "copy",
        "-f", "flv",
        rtmp_output_url,
    ]


def start_live_channel(channel_config: dict, db_update_callback=None) -> dict:
    """
    Start a live transcoding channel.
    channel_config keys:
        channel_id, name, input_url, input_type,
        output_type (HLS/RTMP), output_destination (S3/LOCAL/MEDIAPACKAGE),
        s3_bucket, s3_path, s3_cloudfront_domain, local_path,
        mediapackage_url, mediapackage_user, mediapackage_password,
        rtmp_output_url, master_filename, segment_length,
        hls_list_size, hls_flags, preset, variants
    """
    channel_id = channel_config.get("channel_id") or str(uuid.uuid4())
    name = channel_config.get("name", channel_id)
    ffmpeg_path = "ffmpeg"

    logging.info(f"[LIVE:{name}] Starting channel {channel_id}")

    tmp_dir = tempfile.mkdtemp(prefix=f"live_{channel_id[:8]}_")

    # When destination is LOCAL and a path is provided, write segments directly
    # there; otherwise use a sub-dir of tmp_dir (for S3 / MediaPackage).
    dest = channel_config.get("output_destination", "LOCAL").upper()
    _local_path = channel_config.get("local_path", "").strip()
    if dest == "LOCAL" and _local_path:
        output_dir = _local_path
    else:
        output_dir = os.path.join(tmp_dir, "hls")
    os.makedirs(output_dir, exist_ok=True)

    input_url = channel_config["input_url"]
    input_type = channel_config.get("input_type", "HLS").upper()
    output_type = channel_config.get("output_type", "HLS").upper()

    segment_size = int(channel_config.get("segment_length", 4))
    master_filename = channel_config.get("master_filename", "live")
    preset = channel_config.get("preset", "ultrafast")
    variants = channel_config.get("variants", [])

    if not variants:
        return {"success": False, "error": "No output variants specified"}

    # Build command
    if output_type == "RTMP":
        rtmp_url = channel_config.get("rtmp_output_url", "")
        if not rtmp_url:
            return {"success": False, "error": "RTMP output URL required"}
        ffmpeg_cmd = build_live_rtmp_passthrough_command(input_url, rtmp_url, ffmpeg_path)
    else:
        hls_list_size = int(channel_config.get("hls_list_size", 6))
        hls_flags = channel_config.get("hls_flags", "delete_segments+append_list")
        ffmpeg_cmd = build_live_hls_command(
            input_url=input_url,
            output_dir=output_dir,
            variants=variants,
            segment_size=segment_size,
            master_filename=master_filename,
            preset=preset,
            hls_list_size=hls_list_size,
            hls_flags=hls_flags,
            ffmpeg_path=ffmpeg_path,
            input_type=input_type,
        )

    log_path = os.path.join(_LOGS_DIR, f"live_{channel_id}.log")
    logging.info(f"[LIVE:{name}] FFmpeg cmd: {' '.join(ffmpeg_cmd)}")
    logging.info(f"[LIVE:{name}] FFmpeg log: {log_path}")

    # Start S3 watcher
    observer = handler = periodic = None
    s3_client = None
    if dest == "S3" and output_type == "HLS":
        bucket = channel_config.get("s3_bucket", "")
        s3_prefix = channel_config.get("s3_path", name).strip("/")
        try:
            s3_client = build_s3_client()
            observer, handler, periodic = start_live_upload_watcher(output_dir, bucket, s3_prefix, s3_client)
            logging.info(f"[LIVE:{name}] S3 watcher started: s3://{bucket}/{s3_prefix}")
        except Exception as e:
            logging.error(f"[LIVE:{name}] S3 watcher start failed: {e}")

    with open(log_path, "w") as log_f:
        process = subprocess.Popen(ffmpeg_cmd, stdout=log_f, stderr=log_f)

    lock = threading.Lock()
    _live_locks[channel_id] = lock
    _live_channels[channel_id] = {
        "process": process,
        "tmp_dir": tmp_dir,
        "output_dir": output_dir,
        "log_path": log_path,
        "channel_config": channel_config,
        "observer": observer,
        "handler": handler,
        "periodic": periodic,
        "s3_client": s3_client,
        "started_at": datetime.utcnow().isoformat(),
        "status": "RUNNING",
        "master_filename": master_filename,
        "output_type": output_type,
    }

    if db_update_callback:
        db_update_callback(channel_id, "RUNNING", process.pid)

    _executor.submit(_monitor_live_channel, channel_id, db_update_callback)

    playback_url = _build_live_playback_url(channel_config)
    return {
        "success": True,
        "channel_id": channel_id,
        "status": "RUNNING",
        "playback_url": playback_url,
        "pid": process.pid,
    }


def _build_live_playback_url(config: dict) -> str:
    dest = config.get("output_destination", "LOCAL").upper()
    master = config.get("master_filename", "live")
    if dest == "S3":
        cf = config.get("s3_cloudfront_domain", "").rstrip("/")
        s3_path = config.get("s3_path", "").strip("/")
        if cf:
            return f"{cf}/{s3_path}/{master}.m3u8"
        bucket = config.get("s3_bucket", "")
        return f"https://{bucket}.s3.amazonaws.com/{s3_path}/{master}.m3u8"
    elif dest == "MEDIAPACKAGE":
        return config.get("mediapackage_url", "")
    else:
        local = config.get("local_path", "/tmp/live")
        return f"file://{local}/{master}.m3u8"


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
        logging.warning(f"Watcher stop error: {e}")


def _monitor_live_channel(channel_id: str, db_update_callback=None):
    """Monitor live channel until it ends (usually externally stopped)."""
    pinfo = _live_channels.get(channel_id)
    if not pinfo:
        return

    process = pinfo["process"]
    name = pinfo["channel_config"].get("name", channel_id)

    try:
        process.wait()
    except Exception as e:
        logging.error(f"[LIVE:{name}] Wait error: {e}")
        return

    if channel_id not in _live_channels:
        return

    returncode = process.returncode
    lock = _live_locks.get(channel_id)
    if not lock:
        return

    with lock:
        if channel_id not in _live_channels:
            return
        pinfo = _live_channels[channel_id]
        _stop_watchers(pinfo)

        status = "COMPLETED" if returncode == 0 else "FAILED"
        if returncode != 0:
            logging.error(f"[LIVE:{name}] FFmpeg exited with rc={returncode}")
        pinfo["status"] = status

        if db_update_callback:
            db_update_callback(channel_id, status, None)

        try:
            shutil.rmtree(pinfo["tmp_dir"], ignore_errors=True)
        except Exception:
            pass

        _live_channels.pop(channel_id, None)
        _live_locks.pop(channel_id, None)


def stop_live_channel(channel_id: str, db_update_callback=None) -> dict:
    """Stop a live channel."""
    lock = _live_locks.get(channel_id)
    if not lock:
        return {"success": False, "error": "Channel not found"}

    with lock:
        pinfo = _live_channels.get(channel_id)
        if not pinfo:
            return {"success": False, "error": "Channel not found"}

        process = pinfo["process"]
        name = pinfo["channel_config"].get("name", channel_id)

        _stop_watchers(pinfo)

        try:
            process.terminate()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        except Exception as e:
            logging.error(f"[LIVE:{name}] Stop error: {e}")

        pinfo["status"] = "STOPPED"

        try:
            shutil.rmtree(pinfo["tmp_dir"], ignore_errors=True)
        except Exception:
            pass

        _live_channels.pop(channel_id, None)
        _live_locks.pop(channel_id, None)

        if db_update_callback:
            db_update_callback(channel_id, "STOPPED", None)

        logging.info(f"[LIVE:{name}] Channel {channel_id} stopped")
        return {"success": True, "message": "Channel stopped"}


def get_live_channel_status(channel_id: str) -> dict:
    pinfo = _live_channels.get(channel_id)
    if not pinfo:
        return {"channel_id": channel_id, "status": "NOT_FOUND"}
    return {
        "channel_id": channel_id,
        "status": pinfo.get("status", "RUNNING"),
        "started_at": pinfo.get("started_at"),
        "pid": pinfo["process"].pid if pinfo.get("process") else None,
        "progress_pct": 0,  # Live streams have no known end
    }


def list_active_live_channels() -> list:
    return [
        {"channel_id": cid, "status": info.get("status", "RUNNING"),
         "name": info["channel_config"].get("name", cid),
         "started_at": info.get("started_at")}
        for cid, info in _live_channels.items()
    ]


def get_live_channel_logs(channel_id: str, tail: int = 100) -> str:
    """Get last N lines of FFmpeg log. Works for running AND finished channels."""
    pinfo = _live_channels.get(channel_id)
    if pinfo:
        log_path = pinfo.get("log_path", "")
    else:
        log_path = os.path.join(_LOGS_DIR, f"live_{channel_id}.log")

    if not log_path or not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-tail:])
    except Exception:
        return ""

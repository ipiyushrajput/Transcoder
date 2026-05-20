import subprocess
import json
import logging
import requests
import os
import ssl
import urllib.request
import urllib.parse


def validate_input_url(url: str) -> dict:
    """
    Validate input URL accessibility. Returns dict with:
    - valid: bool
    - message: str
    - probe: dict (ffprobe output if available)
    """
    result = {"valid": False, "message": "", "probe": None}

    if not url:
        result["message"] = "Input URL is empty"
        return result

    # HTTP/HTTPS URL check
    if url.startswith(("http://", "https://")):
        try:
            resp = requests.head(url, timeout=15, allow_redirects=True, verify=False)
            if resp.status_code == 405:
                resp = requests.get(url, timeout=15, allow_redirects=True, verify=False, stream=True)
            if resp.status_code == 403:
                result["message"] = "Access denied (HTTP 403)"
                return result
            elif resp.status_code == 404:
                result["message"] = "File not found (HTTP 404)"
                return result
            elif resp.status_code >= 400:
                result["message"] = f"HTTP error {resp.status_code}"
                return result
            result["valid"] = True
            result["message"] = "URL is accessible"
        except requests.exceptions.ConnectionError:
            result["message"] = "Cannot connect to URL"
            return result
        except requests.exceptions.Timeout:
            result["message"] = "Connection timeout"
            return result
        except Exception as e:
            result["message"] = f"URL check failed: {str(e)}"
            return result

    # S3 URL (s3://)
    elif url.startswith("s3://"):
        result["valid"] = True
        result["message"] = "S3 URL accepted"

    # RTMP / SRT - can't HEAD these, accept as-is
    elif url.startswith(("rtmp://", "rtmps://", "srt://")):
        result["valid"] = True
        result["message"] = "Stream URL accepted"

    # Local file
    else:
        if os.path.exists(url):
            if os.access(url, os.R_OK):
                result["valid"] = True
                result["message"] = "Local file is accessible"
            else:
                result["message"] = "Local file is not readable (permission denied)"
                return result
        else:
            result["message"] = f"File not found: {url}"
            return result

    # Run ffprobe if URL is valid
    if result["valid"]:
        probe = run_ffprobe(url)
        if probe:
            result["probe"] = probe

    return result


def run_ffprobe(url: str) -> dict:
    """Run ffprobe and return stream info as dict."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            "-analyzeduration", "10000000",
            "-probesize", "10000000",
        ]

        # For RTMP/SRT live streams, limit analysis time
        if url.startswith(("rtmp://", "srt://")):
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_streams", "-show_format", "-t", "5",
                   "-analyzeduration", "5000000", "-probesize", "5000000"]

        cmd.append(url)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
        else:
            logging.warning(f"ffprobe failed for {url}: {result.stderr[:200]}")
            return None
    except FileNotFoundError:
        logging.warning("ffprobe not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logging.warning(f"ffprobe timeout for {url}")
        return None
    except Exception as e:
        logging.warning(f"ffprobe error: {e}")
        return None


def parse_probe_info(probe: dict) -> dict:
    """Extract human-readable info from ffprobe output."""
    if not probe:
        return {}

    info = {
        "format": {},
        "video": [],
        "audio": [],
        "subtitle": [],
    }

    fmt = probe.get("format", {})
    info["format"] = {
        "container": fmt.get("format_long_name", fmt.get("format_name", "Unknown")),
        "duration": round(float(fmt.get("duration", 0)), 2) if fmt.get("duration") else None,
        "size_mb": round(int(fmt.get("size", 0)) / 1024 / 1024, 2) if fmt.get("size") else None,
        "bitrate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else None,
    }

    for stream in probe.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video":
            info["video"].append({
                "codec": stream.get("codec_name"),
                "profile": stream.get("profile"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "fps": stream.get("avg_frame_rate"),
                "bitrate_kbps": round(int(stream.get("bit_rate", 0)) / 1000) if stream.get("bit_rate") else None,
                "pixel_format": stream.get("pix_fmt"),
            })
        elif codec_type == "audio":
            info["audio"].append({
                "codec": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "sample_rate": stream.get("sample_rate"),
                "bitrate_kbps": round(int(stream.get("bit_rate", 0)) / 1000) if stream.get("bit_rate") else None,
                "language": stream.get("tags", {}).get("language"),
            })
        elif codec_type == "subtitle":
            info["subtitle"].append({
                "codec": stream.get("codec_name"),
                "language": stream.get("tags", {}).get("language"),
            })

    return info

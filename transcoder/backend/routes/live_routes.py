import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from database import get_db, close_db, Job, JobVariant
from input_validator import validate_input_url, parse_probe_info
from live_transcoder import start_live_channel, stop_live_channel, get_live_channel_status

live_bp = Blueprint("live", __name__, url_prefix="/api/live")


def _save_live_job_to_db(channel_config: dict, channel_id: str, playback_url: str):
    db = get_db()
    if not db:
        return
    try:
        job = Job(
            job_id=channel_id,
            type="LIVE",
            status="RUNNING",
            name=channel_config.get("name", channel_id),
            input_url=channel_config.get("input_url"),
            input_type=channel_config.get("input_type"),
            output_type=channel_config.get("output_type", "HLS"),
            output_destination=channel_config.get("output_destination", "LOCAL"),
            s3_bucket=channel_config.get("s3_bucket"),
            s3_path=channel_config.get("s3_path"),
            s3_cloudfront_domain=channel_config.get("s3_cloudfront_domain"),
            local_path=channel_config.get("local_path"),
            mediapackage_url=channel_config.get("mediapackage_url"),
            mediapackage_user=channel_config.get("mediapackage_user"),
            mediapackage_password=channel_config.get("mediapackage_password"),
            rtmp_output_url=channel_config.get("rtmp_output_url"),
            master_filename=channel_config.get("master_filename", "live"),
            segment_length=channel_config.get("segment_length", 4),
            hls_list_size=channel_config.get("hls_list_size", 6),
            hls_flags=channel_config.get("hls_flags"),
            preset=channel_config.get("preset", "ultrafast"),
            playback_url=playback_url,
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()

        for v in channel_config.get("variants", []):
            variant = JobVariant(
                job_id=channel_id,
                width=v.get("width"),
                height=v.get("height"),
                video_codec=v.get("video_codec", "libx264"),
                video_bitrate=v.get("video_bitrate"),
                framerate=str(v.get("framerate", "25")),
                gop=v.get("gop"),
                reference_frames=v.get("reference_frames"),
                profile=v.get("profile"),
                level=str(v.get("level", "")),
                audio_codec=v.get("audio_codec", "aac"),
                audio_bitrate=v.get("audio_bitrate"),
                sample_rate=v.get("sample_rate"),
            )
            db.add(variant)

        db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"DB save live channel failed: {e}")
    finally:
        close_db(db)


def _update_live_status_in_db(channel_id: str, status: str, pid: int = None, error_message: str = None):
    db = get_db()
    if not db:
        return
    try:
        job = db.query(Job).filter(Job.job_id == channel_id).first()
        if job:
            job.status = status
            if pid is not None:
                job.process_pid = pid
            if status in ("COMPLETED", "FAILED", "STOPPED"):
                job.completed_at = datetime.utcnow()
            if error_message is not None:
                job.error_message = error_message
            db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"DB update live status failed: {e}")
    finally:
        close_db(db)


@live_bp.route("/validate-input", methods=["POST"])
def validate_input():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    result = validate_input_url(url)
    probe_info = None
    if result.get("probe"):
        probe_info = parse_probe_info(result["probe"])

    return jsonify({
        "valid": result["valid"],
        "message": result["message"],
        "probe": probe_info,
    }), 200 if result["valid"] else 400


@live_bp.route("/start", methods=["POST"])
def start_channel():
    data = request.get_json() or {}

    required = ["input_url", "variants"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    variants = data.get("variants", [])
    if not variants:
        return jsonify({"error": "At least one output variant is required"}), 400

    channel_id = str(uuid.uuid4())

    channel_config = {
        "channel_id": channel_id,
        "name": data.get("name", f"live-{channel_id[:8]}"),
        "input_url": data["input_url"].strip(),
        "input_type": data.get("input_type", "HLS"),
        "output_type": data.get("output_type", "HLS"),
        "output_destination": data.get("output_destination", "LOCAL"),
        "s3_bucket": data.get("s3_bucket", ""),
        "s3_path": data.get("s3_path", ""),
        "s3_cloudfront_domain": data.get("s3_cloudfront_domain", ""),
        "local_path": data.get("local_path", ""),
        "mediapackage_url": data.get("mediapackage_url", ""),
        "mediapackage_user": data.get("mediapackage_user", ""),
        "mediapackage_password": data.get("mediapackage_password", ""),
        "rtmp_output_url": data.get("rtmp_output_url", ""),
        "master_filename": data.get("master_filename", "live"),
        "segment_length": int(data.get("segment_length", 4)),
        "hls_list_size": int(data.get("hls_list_size", 6)),
        "hls_flags": data.get("hls_flags", "delete_segments+append_list"),
        "preset": data.get("preset", "ultrafast"),
        "variants": variants,
    }

    result = start_live_channel(channel_config, db_update_callback=_update_live_status_in_db)

    if not result["success"]:
        return jsonify({"error": result.get("error", "Failed to start channel")}), 500

    _save_live_job_to_db(channel_config, channel_id, result.get("playback_url", ""))

    return jsonify({
        "message": "Live channel started successfully",
        "channel_id": channel_id,
        "status": "RUNNING",
        "playback_url": result.get("playback_url"),
    }), 200


@live_bp.route("/stop", methods=["POST"])
def stop_channel():
    data = request.get_json() or {}
    channel_id = data.get("channel_id", "").strip()
    if not channel_id:
        return jsonify({"error": "channel_id is required"}), 400

    result = stop_live_channel(channel_id, db_update_callback=_update_live_status_in_db)
    if not result["success"]:
        return jsonify({"error": result.get("error", "Failed to stop channel")}), 400

    return jsonify({"message": result["message"], "channel_id": channel_id}), 200


@live_bp.route("/status/<channel_id>", methods=["GET"])
def channel_status(channel_id):
    status = get_live_channel_status(channel_id)
    return jsonify(status), 200

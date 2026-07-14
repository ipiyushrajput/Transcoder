import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from database import get_db, close_db, Job, JobVariant, JobClip
from input_validator import validate_input_url, parse_probe_info
from vod_transcoder import start_vod_job, stop_vod_job, get_vod_job_status
from av1_utils import validate_av1_variants

vod_bp = Blueprint("vod", __name__, url_prefix="/api/vod")


def _save_job_to_db(job_config: dict, job_id: str, playback_url: str):
    db = get_db()
    if not db:
        return
    try:
        job = Job(
            job_id=job_id,
            type="VOD",
            status="RUNNING",
            name=job_config.get("name", job_id),
            input_url=job_config.get("input_url"),
            input_type=job_config.get("input_type"),
            output_type=job_config.get("output_type", "HLS"),
            output_destination=job_config.get("output_destination", "LOCAL"),
            s3_bucket=job_config.get("s3_bucket"),
            s3_path=job_config.get("s3_path"),
            s3_cloudfront_domain=job_config.get("s3_cloudfront_domain"),
            local_path=job_config.get("local_path"),
            master_filename=job_config.get("master_filename", "master"),
            segment_length=job_config.get("segment_length", 6),
            hls_playlist_type=job_config.get("hls_playlist_type", "vod"),
            hls_flags=job_config.get("hls_flags"),
            hls_list_size=job_config.get("hls_list_size"),
            preset=job_config.get("preset", "medium"),
            subtitle_url=job_config.get("subtitle_url"),
            subtitle_language=job_config.get("subtitle_language", "en"),
            esam_enabled=job_config.get("esam_enabled", False),
            esam_scc_xml=job_config.get("esam_scc_xml"),
            esam_mcc_xml=job_config.get("esam_mcc_xml"),
            playback_url=playback_url,
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()

        for i, v in enumerate(job_config.get("variants", [])):
            variant = JobVariant(
                job_id=job_id,
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
                av1_preset=v.get("av1_preset"),
                av1_segment_ext=v.get("av1_segment_ext"),
            )
            db.add(variant)

        for i, clip in enumerate(job_config.get("clips", [])):
            c = JobClip(
                job_id=job_id,
                start_timecode=clip.get("start_timecode"),
                end_timecode=clip.get("end_timecode"),
                clip_order=i,
            )
            db.add(c)

        db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"DB save job failed: {e}")
    finally:
        close_db(db)


def _update_job_status_in_db(job_id: str, status: str, pid: int = None, error_message: str = None):
    db = get_db()
    if not db:
        return
    try:
        job = db.query(Job).filter(Job.job_id == job_id).first()
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
        logging.error(f"DB update status failed: {e}")
    finally:
        close_db(db)


@vod_bp.route("/validate-input", methods=["POST"])
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


@vod_bp.route("/start", methods=["POST"])
def start_job():
    data = request.get_json() or {}

    # Required fields validation
    required = ["input_url", "variants"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    variants = data.get("variants", [])
    if not variants:
        return jsonify({"error": "At least one output variant is required"}), 400

    # Validate each variant
    for i, v in enumerate(variants):
        if not v.get("width") or not v.get("height"):
            return jsonify({"error": f"Variant {i+1}: width and height are required"}), 400
        if not v.get("video_bitrate"):
            return jsonify({"error": f"Variant {i+1}: video_bitrate is required"}), 400

    # Reject AV1 encoders this FFmpeg build lacks (avoids a mid-encode
    # "Option not found" failure on -svtav1-params/-aom-params/etc.).
    av1_error = validate_av1_variants(variants)
    if av1_error:
        return jsonify({"error": av1_error}), 400

    job_id = str(uuid.uuid4())

    job_config = {
        "job_id": job_id,
        "name": data.get("name", f"vod-{job_id[:8]}"),
        "input_url": data["input_url"].strip(),
        "input_type": data.get("input_type", "FILE"),
        "clips": data.get("clips", []),
        "subtitle_url": data.get("subtitle_url"),
        "subtitle_language": data.get("subtitle_language", "en"),
        "output_type": data.get("output_type", "HLS"),
        "output_destination": data.get("output_destination", "LOCAL"),
        "s3_bucket": data.get("s3_bucket", ""),
        "s3_path": data.get("s3_path", ""),
        "s3_cloudfront_domain": data.get("s3_cloudfront_domain", ""),
        "local_path": data.get("local_path", ""),
        "master_filename": data.get("master_filename", "master"),
        "segment_length": int(data.get("segment_length", 6)),
        "hls_playlist_type": data.get("hls_playlist_type", "vod"),
        "hls_flags": data.get("hls_flags", "independent_segments"),
        "hls_list_size": data.get("hls_list_size", 0),
        "preset": data.get("preset", "medium"),
        "variants": variants,
        "esam_enabled": bool(data.get("esam_enabled", False)),
        "esam_scc_xml": data.get("esam_scc_xml", ""),
        "esam_mcc_xml": data.get("esam_mcc_xml", ""),
    }

    result = start_vod_job(job_config, db_update_callback=_update_job_status_in_db)

    if not result["success"]:
        return jsonify({"error": result.get("error", "Failed to start job")}), 500

    # Save to DB
    _save_job_to_db(job_config, job_id, result.get("playback_url", ""))

    return jsonify({
        "message": "VOD job started successfully",
        "job_id": job_id,
        "status": "RUNNING",
        "playback_url": result.get("playback_url"),
    }), 200


@vod_bp.route("/stop", methods=["POST"])
def stop_job():
    data = request.get_json() or {}
    job_id = data.get("job_id", "").strip()
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    result = stop_vod_job(job_id, db_update_callback=_update_job_status_in_db)
    if not result["success"]:
        return jsonify({"error": result.get("error", "Failed to stop job")}), 400

    return jsonify({"message": result["message"], "job_id": job_id}), 200


@vod_bp.route("/status/<job_id>", methods=["GET"])
def job_status(job_id):
    status = get_vod_job_status(job_id)
    return jsonify(status), 200

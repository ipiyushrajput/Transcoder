from flask import Blueprint, request, jsonify
import logging
from database import get_db, close_db, Job, JobVariant, JobClip
from input_validator import validate_input_url, run_ffprobe, parse_probe_info
from vod_transcoder import list_active_vod_jobs, get_vod_job_status, get_vod_job_logs
from live_transcoder import list_active_live_channels, get_live_channel_status, get_live_channel_logs

common_bp = Blueprint("common", __name__, url_prefix="/api")

TEMPLATES = {
    "4K_AVC": {
        "label": "4K (AVC - H.264)",
        "variants": [
            {"width": 3840, "height": 2160, "video_codec": "libx264", "video_bitrate": 12000000,
             "framerate": "30", "gop": 90, "reference_frames": 4, "profile": "main", "level": "5.1",
             "audio_codec": "aac", "audio_bitrate": 192000, "sample_rate": 48000},
            {"width": 1920, "height": 1080, "video_codec": "libx264", "video_bitrate": 5000000,
             "framerate": "30", "gop": 90, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 1280, "height": 720, "video_codec": "libx264", "video_bitrate": 3000000,
             "framerate": "30", "gop": 90, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
        ],
    },
    "4K_HEVC": {
        "label": "4K (HEVC - H.265)",
        "variants": [
            {"width": 3840, "height": 2160, "video_codec": "libx265", "video_bitrate": 8000000,
             "framerate": "30", "gop": 90, "reference_frames": 4, "profile": "main", "level": "5.1",
             "audio_codec": "aac", "audio_bitrate": 192000, "sample_rate": 48000},
            {"width": 1920, "height": 1080, "video_codec": "libx265", "video_bitrate": 3200000,
             "framerate": "30", "gop": 90, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 1280, "height": 720, "video_codec": "libx265", "video_bitrate": 1700000,
             "framerate": "30", "gop": 90, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
        ],
    },
    "FHD_AVC": {
        "label": "Full HD (AVC - H.264)",
        "variants": [
            {"width": 1920, "height": 1080, "video_codec": "libx264", "video_bitrate": 4000000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 1280, "height": 720, "video_codec": "libx264", "video_bitrate": 2000000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 960, "height": 540, "video_codec": "libx264", "video_bitrate": 1000000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 640, "height": 360, "video_codec": "libx264", "video_bitrate": 700000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.0",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
        ],
    },
    "FHD_HEVC": {
        "label": "Full HD (HEVC - H.265)",
        "variants": [
            {"width": 1920, "height": 1080, "video_codec": "libx265", "video_bitrate": 3000000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 1280, "height": 720, "video_codec": "libx265", "video_bitrate": 1500000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 960, "height": 540, "video_codec": "libx265", "video_bitrate": 700000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 640, "height": 360, "video_codec": "libx265", "video_bitrate": 400000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.0",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
        ],
    },
    "HD": {
        "label": "HD (720p)",
        "variants": [
            {"width": 1280, "height": 720, "video_codec": "libx264", "video_bitrate": 2000000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "4.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 960, "height": 540, "video_codec": "libx264", "video_bitrate": 1000000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.1",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
            {"width": 640, "height": 360, "video_codec": "libx264", "video_bitrate": 700000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.0",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
        ],
    },
    "SD": {
        "label": "SD (360p)",
        "variants": [
            {"width": 640, "height": 360, "video_codec": "libx264", "video_bitrate": 700000,
             "framerate": "25", "gop": 60, "reference_frames": 4, "profile": "main", "level": "3.0",
             "audio_codec": "aac", "audio_bitrate": 128000, "sample_rate": 48000},
        ],
    },
}


@common_bp.route("/templates", methods=["GET"])
def get_templates():
    return jsonify(TEMPLATES), 200


@common_bp.route("/probe", methods=["POST"])
def probe_input():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    validation = validate_input_url(url)
    probe_info = None
    if validation.get("probe"):
        probe_info = parse_probe_info(validation["probe"])

    return jsonify({
        "valid": validation["valid"],
        "message": validation["message"],
        "probe": probe_info,
        "raw_probe": validation.get("probe"),
    }), 200 if validation["valid"] else 400


@common_bp.route("/jobs", methods=["GET"])
def list_jobs():
    db = get_db()
    if db is None:
        return jsonify({"error": "Database unavailable"}), 503

    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        job_type = request.args.get("type")
        status = request.args.get("status")

        query = db.query(Job)
        if job_type:
            query = query.filter(Job.type == job_type.upper())
        if status:
            query = query.filter(Job.status == status.upper())

        total = query.count()
        jobs = query.order_by(Job.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

        job_list = []
        for j in jobs:
            d = _serialize_job(j)
            if j.status == "RUNNING":
                try:
                    if j.type == "VOD":
                        s = get_vod_job_status(j.job_id)
                    else:
                        s = get_live_channel_status(j.job_id)
                    d["progress_pct"] = s.get("progress_pct", 0)
                except Exception:
                    d["progress_pct"] = 0
            elif j.status == "COMPLETED":
                d["progress_pct"] = 100
            else:
                d["progress_pct"] = None
            job_list.append(d)

        return jsonify({
            "total": total,
            "page": page,
            "per_page": per_page,
            "jobs": job_list,
        }), 200
    except Exception as e:
        logging.error(f"List jobs error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)


@common_bp.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    db = get_db()
    if db is None:
        return jsonify({"error": "Database unavailable"}), 503

    try:
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if not job:
            return jsonify({"error": "Job not found"}), 404

        variants = db.query(JobVariant).filter(JobVariant.job_id == job_id).all()
        clips = db.query(JobClip).filter(JobClip.job_id == job_id).order_by(JobClip.clip_order).all()

        job_data = _serialize_job(job)
        job_data["variants"] = [_serialize_variant(v) for v in variants]
        job_data["clips"] = [_serialize_clip(c) for c in clips]

        # Merge live status if job is running
        if job.status == "RUNNING":
            if job.type == "VOD":
                live_status = get_vod_job_status(job_id)
            else:
                live_status = get_live_channel_status(job_id)
            if live_status.get("status") not in ("NOT_FOUND",):
                job_data["live_status"] = live_status

        return jsonify(job_data), 200
    except Exception as e:
        logging.error(f"Get job error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)


@common_bp.route("/jobs/<job_id>/logs", methods=["GET"])
def get_job_logs(job_id):
    tail = int(request.args.get("tail", 100))
    db = get_db()
    job = None
    if db:
        try:
            job = db.query(Job).filter(Job.job_id == job_id).first()
        finally:
            close_db(db)

    if job and job.type == "LIVE":
        logs = get_live_channel_logs(job_id, tail)
    else:
        logs = get_vod_job_logs(job_id, tail)

    return jsonify({"job_id": job_id, "logs": logs}), 200


@common_bp.route("/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    db = get_db()
    if db is None:
        return jsonify({"error": "Database unavailable"}), 503
    try:
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.status == "RUNNING":
            return jsonify({"error": "Cannot delete a running job. Stop it first."}), 400
        db.delete(job)
        db.commit()
        return jsonify({"message": "Job deleted"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)


@common_bp.route("/status", methods=["GET"])
def system_status():
    vod_jobs = list_active_vod_jobs()
    live_channels = list_active_live_channels()
    return jsonify({
        "active_vod_jobs": len(vod_jobs),
        "active_live_channels": len(live_channels),
        "vod_jobs": vod_jobs,
        "live_channels": live_channels,
    }), 200


def _serialize_job(j: Job) -> dict:
    return {
        "id": j.id,
        "job_id": j.job_id,
        "type": j.type,
        "status": j.status,
        "name": j.name,
        "input_url": j.input_url,
        "input_type": j.input_type,
        "output_type": j.output_type,
        "output_destination": j.output_destination,
        "s3_bucket": j.s3_bucket,
        "s3_path": j.s3_path,
        "local_path": j.local_path,
        "master_filename": j.master_filename,
        "segment_length": j.segment_length,
        "preset": j.preset,
        "playback_url": j.playback_url,
        "error_message": j.error_message,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


def _serialize_variant(v: JobVariant) -> dict:
    return {
        "id": v.id,
        "width": v.width,
        "height": v.height,
        "video_codec": v.video_codec,
        "video_bitrate": v.video_bitrate,
        "framerate": v.framerate,
        "gop": v.gop,
        "reference_frames": v.reference_frames,
        "profile": v.profile,
        "level": v.level,
        "audio_codec": v.audio_codec,
        "audio_bitrate": v.audio_bitrate,
        "sample_rate": v.sample_rate,
    }


def _serialize_clip(c: JobClip) -> dict:
    return {
        "id": c.id,
        "start_timecode": c.start_timecode,
        "end_timecode": c.end_timecode,
        "clip_order": c.clip_order,
    }

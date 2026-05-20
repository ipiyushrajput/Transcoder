#!/usr/bin/env python3
import logging
import argparse
import subprocess
import os
import shutil
import json
import urllib.parse
import urllib.request
import tempfile
import fractions
import time
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
from datetime import datetime

def is_url(path):
    """Check if the given path is a URL (http or https)."""
    if not path:
        return False
    parsed = urllib.parse.urlparse(path)
    return parsed.scheme in ('http', 'https')

def validate_url(url):
    """Validate if the URL is accessible."""
    try:
        req = urllib.request.Request(url, method='HEAD')
        # Create SSL context with verification disabled to handle certificate issues
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            return response.status == 200
    except Exception as e:
        logging.error(f"URL validation failed for {url}: {e}")
        return False

def setup_logging(args, config):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers to avoid duplicate logs in interactive sessions
    if logger.hasHandlers():
        logger.handlers.clear()

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)

    # File handler
    log_file_path = args.log_file or config.get("defaults", {}).get("log_file")
    if not log_file_path:
        program_name = Path(sys.argv[0]).stem
        log_file_path = f"{program_name}_{datetime.now():%Y%m%d_%H%M%S}.log"
        log_file_path = str(Path.cwd() / log_file_path)

    Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_file_path)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'))
    logger.addHandler(fh)

    logging.info(f"All logs will be written to: {log_file_path}")

def run_loudnorm_analysis(ffmpeg_executable, input_video, duration=None, cwd=None):
    ffmpeg_cmd = [
        ffmpeg_executable,
        "-y",
    ]
    if duration is not None:
        ffmpeg_cmd.extend(["-t", str(duration)])
    if "ffconcat" in os.path.basename(input_video):
        ffmpeg_cmd.extend(["-safe", "0"])

    ffmpeg_cmd.extend([
        "-i", input_video,
        "-vn",  # No video output
        "-af", "loudnorm=print_format=json",  # Apply loudnorm filter and print JSON
        "-f", "null", "-"  # Output to null
    ])

    try:
        result = subprocess.run(
            ffmpeg_cmd,
            check=True,
            stdout=subprocess.DEVNULL,  # Ignore stdout
            stderr=subprocess.PIPE,      # Capture stderr (loudnorm prints JSON here)
            text=True,
            cwd=cwd
        )

        json_lines = []
        in_json_block = False
        for line in result.stderr.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                in_json_block = True
            if in_json_block:
                json_lines.append(line)
                if line.endswith("}"):
                    break

        if not json_lines:
            logging.error("Could not find JSON output from loudnorm analysis.")
            return None

        # Join multiple lines and parse JSON
        json_str = "".join(json_lines)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse loudnorm JSON: {e}")
            logging.error(f"JSON content:\n{json_str}")
            return None

    except subprocess.CalledProcessError as e:
        logging.error(f"Loudnorm analysis failed: {e}")
        logging.error(f"FFmpeg stderr:\n{e.stderr}")
        return None

def timecode_to_seconds(tc: str, fps: float) -> float:
    """
    Convert SMPTE timecode 'HH:MM:SS:FF' to seconds for FFmpeg.
    tc:  timecode string
    fps: frame rate (e.g., 25, 29.97, 30)
    """
    parts = tc.split(':')
    if len(parts) != 4:
        raise ValueError("Timecode must be in HH:MM:SS:FF format")

    hh, mm, ss, ff = map(int, parts)

    seconds = hh * 3600 + mm * 60 + ss + ff / fps
    return round(seconds, 5)

def get_video_fps(ffprobe_executable, input_video):
    # Validate URL if it's a URL
    if is_url(input_video):
        if not validate_url(input_video):
            logging.error(f"Error: Cannot access video URL: {input_video}")
            return 25.0
        logging.info(f"Processing video from URL: {input_video}")
    
    ffprobe_cmd = [
        ffprobe_executable,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_video
    ]
    try:
        result = subprocess.run(ffprobe_cmd, check=True, capture_output=True, text=True)
        avg_frame_rate_str = result.stdout.strip()
        if avg_frame_rate_str:
            try:
                # Use Fraction to handle frame rates like "30000/1001"
                fps_fraction = fractions.Fraction(avg_frame_rate_str)
                return float(fps_fraction)
            except ValueError:
                logging.warning(f"Warning: Could not parse FPS '{avg_frame_rate_str}' as a fraction. Attempting float conversion.")
                return float(avg_frame_rate_str)
        else:
            logging.warning("Warning: FFprobe returned empty FPS. Defaulting to 25 FPS.")
            return 25.0
    except FileNotFoundError:
        logging.error(f"Error: ffprobe executable not found at '{ffprobe_executable}'. Please ensure it's in the same directory as ffmpeg or in your PATH.")
        return 25.0
    except Exception as e:
        logging.warning(f"Warning: Error getting video FPS: {e}. Defaulting to 25 FPS.")
        return 25.0

def process_clippings(input_video, ffmpeg_executable, clippings, video_fps, subtitle_file=None):
    temp_dir = tempfile.mkdtemp(prefix="hls_clippings_", dir=".")
    video_ffconcat_path = os.path.join(temp_dir, "video_input.ffconcat")
    subtitle_ffconcat_path = os.path.join(temp_dir, "subtitle_input.ffconcat") if subtitle_file else None

    logging.info(f"Processing {len(clippings)} input clipping(s) in temporary directory: {temp_dir}")
    logging.info(f"Using video FPS for timecode conversion: {video_fps}")

    # For Video (new method)
    video_ffconcat_content = ["ffconcat version 1.0"]
    abs_input_video = os.path.abspath(input_video)

    # For Subtitles (old method)
    clipped_subtitle_files = []

    has_valid_clippings = False

    for i, clip in enumerate(clippings):
        start_timecode = clip.get("StartTimecode")
        end_timecode = clip.get("EndTimecode")

        if not start_timecode or not end_timecode:
            logging.warning(f"Warning: Clipping {i+1} is missing StartTimecode or EndTimecode. Skipping.")
            continue

        start_seconds = timecode_to_seconds(start_timecode, video_fps)
        end_seconds = timecode_to_seconds(end_timecode, video_fps)
        duration_seconds = end_seconds - start_seconds

        if duration_seconds <= 0:
            logging.warning(f"Warning: Clipping {i+1} has non-positive duration ({duration_seconds}s). Skipping.")
            continue

        has_valid_clippings = True

        # Video processing (in-memory)
        video_ffconcat_content.append(f"\nfile '{abs_input_video}'")
        video_ffconcat_content.append(f"inpoint {start_seconds}")
        video_ffconcat_content.append(f"outpoint {end_seconds}")

        # Subtitle processing (creating physical clip files)
        if subtitle_file:
            output_subtitle_clip_path = os.path.join(temp_dir, f"clip_{i:03d}.vtt")
            sub_clip_cmd = [
                ffmpeg_executable,
                "-y",
                "-i", subtitle_file,
                "-ss", str(start_seconds),
                "-t", str(duration_seconds),
                "-c:s", "webvtt",
                output_subtitle_clip_path
            ]
            logging.info(f"Executing subtitle clipping command for segment {i+1}.")
            try:
                subprocess.run(sub_clip_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                clipped_subtitle_files.append(output_subtitle_clip_path)
            except subprocess.CalledProcessError as e:
                logging.error(f"Error during subtitle clipping for segment {i+1}: {e}\nStderr:\n{e.stderr}")
                shutil.rmtree(temp_dir)
                return None, None, None

    if not has_valid_clippings:
        logging.warning("No valid clippings to process.")
        shutil.rmtree(temp_dir)
        return None, None, None

    # Write video ffconcat file
    with open(video_ffconcat_path, "w") as f:
        f.write("\n".join(video_ffconcat_content))
    logging.info(f"Generated video ffconcat file: {video_ffconcat_path}")

    # Write subtitle ffconcat file if needed
    if subtitle_ffconcat_path and clipped_subtitle_files:
        with open(subtitle_ffconcat_path, "w") as f:
            f.write("ffconcat version 1.0\n")
            for fpath in clipped_subtitle_files:
                f.write(f"file '{os.path.abspath(fpath)}'\n")
        logging.info(f"Generated subtitle ffconcat file: {subtitle_ffconcat_path}")
    elif subtitle_file:
        # This case happens if there's a subtitle file but no valid clippings were generated.
        subtitle_ffconcat_path = None

    return video_ffconcat_path, subtitle_ffconcat_path, temp_dir

def process_subtitles(ffmpeg_executable, input_path, output_dir, sub_lang, duration=None):
    """
    Generates a separate HLS playlist for subtitles.
    """
    if not input_path:
        logging.info("No subtitle file provided, skipping subtitle processing.")
        return True
    
    # Handle URL validation for subtitles
    if is_url(input_path):
        if not validate_url(input_path):
            logging.error(f"Error: Cannot access subtitle URL: {input_path}")
            return False
        logging.info(f"Processing subtitle from URL: {input_path}")
    elif not os.path.exists(input_path):
        logging.info(f"Subtitle file not found: {input_path}, skipping subtitle processing.")
        return True

    subtitle_playlist_name = f"channel_{sub_lang}-vtt.m3u8"
    subtitle_segment_name = f"channel_{sub_lang}-vtt_%05d.vtt"
    subtitle_playlist_path = os.path.join(output_dir, subtitle_playlist_name)
    subtitle_segment_path = os.path.join(output_dir, subtitle_segment_name)

    ffmpeg_cmd = [
        ffmpeg_executable,
        "-y",
    ]

    if duration is not None:
        ffmpeg_cmd.extend(["-t", str(duration)])

    is_concat = "ffconcat" in os.path.basename(input_path)
    if is_concat:
        ffmpeg_cmd.extend(["-safe", "0"])

    ffmpeg_cmd.extend(["-i", input_path])

    # For a subtitle-only ffconcat or a direct subtitle file, the stream to map is always the first one.
    ffmpeg_cmd.extend(["-map", "0:0"])

    ffmpeg_cmd.extend([
        "-c:s", "webvtt",
        "-f", "segment",
        "-segment_time", "6",
        "-segment_list_type", "m3u8",
        "-hls_playlist_type", "vod",
        "-segment_list", subtitle_playlist_path,
        "-segment_format", "webvtt",
        subtitle_segment_path,
    ])

    logging.info(f"Executing FFmpeg command for subtitles. Command and arguments: {ffmpeg_cmd}")
    try:
        result = subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        logging.info("Subtitle HLS generation completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error during subtitle HLS generation: {e}")
        logging.error(f"FFmpeg stderr:\n{e.stderr}")
        return False
    except FileNotFoundError:
        logging.error(f"Error: FFmpeg executable '{ffmpeg_executable}' not found for subtitle processing.")
        return False

def update_master_playlist_for_subtitles(master_playlist_path, sub_lang):
    """
    Updates the master M3U8 playlist to reference the subtitle playlist and ensures
    #EXT-X-VERSION:3 and #EXT-X-INDEPENDENT-SEGMENTS are present.
    """
    if not os.path.exists(master_playlist_path):
        logging.error(f"Master playlist not found at {master_playlist_path}, cannot update.")
        return

    subtitle_playlist_name = f"channel_{sub_lang}-vtt.m3u8"

    with open(master_playlist_path, "r") as f:
        lines = f.readlines()

    updated_lines = []
    has_subtitle_info_in_stream_inf = False
    has_subtitle_media_tag = False

    # Process existing lines to check for presence of tags and collect stream-inf lines
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF"):
            if 'SUBTITLES="subs"' in line:
                has_subtitle_info_in_stream_inf = True
        elif line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"):
            has_subtitle_media_tag = True

    # Construct the new playlist content
    updated_lines.append("#EXTM3U\n")
    updated_lines.append("#EXT-X-VERSION:3\n")
    updated_lines.append("#EXT-X-INDEPENDENT-SEGMENTS\n")

    # Add other lines, skipping duplicates of the above and ensuring subtitle info
    for line in lines:
        stripped_line = line.strip()
        if stripped_line == "#EXTM3U" or \
           stripped_line.startswith("#EXT-X-VERSION:") or \
           stripped_line == "#EXT-X-INDEPENDENT-SEGMENTS":
            continue # Already added or will be added in a controlled manner

        if line.startswith("#EXT-X-STREAM-INF"):
            if not has_subtitle_info_in_stream_inf:
                # Add SUBTITLES="subs" attribute if not already present
                updated_lines.append(line.strip() + ',SUBTITLES="subs"\n')
            else:
                updated_lines.append(line)
        elif not line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"): # Avoid adding subtitle media tag twice
            updated_lines.append(line)

    # Add the EXT-X-MEDIA tag for subtitles if not already present
    if not has_subtitle_media_tag:
        subtitle_media_tag = (
            f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",DEFAULT=YES,AUTOSELECT=YES,'
            f'FORCED=NO,LANGUAGE="{sub_lang}",URI="{subtitle_playlist_name}"\n'
        )
        updated_lines.append(subtitle_media_tag)

    with open(master_playlist_path, "w") as f:
        f.writelines(updated_lines)

    logging.info(f"Updated master playlist {master_playlist_path} with version, independent segments, and subtitle information.")

def update_subtitle_playlist(subtitle_playlist_path):
    """
    Ensures #EXT-X-PLAYLIST-TYPE:VOD and #EXT-X-VERSION:3 are present in the subtitle playlist.
    """
    if not os.path.exists(subtitle_playlist_path):
        logging.error(f"Subtitle playlist not found at {subtitle_playlist_path}, cannot update.")
        return

    with open(subtitle_playlist_path, "r") as f:
        lines = f.readlines()

    updated_lines = []

    updated_lines.append("#EXTM3U\n")
    updated_lines.append("#EXT-X-VERSION:3\n")
    updated_lines.append("#EXT-X-PLAYLIST-TYPE:VOD\n")

    # Add other lines, skipping duplicates of the above
    for line in lines:
        stripped_line = line.strip()
        if stripped_line == "#EXTM3U" or \
           stripped_line.startswith("#EXT-X-VERSION:") or \
           stripped_line == "#EXT-X-PLAYLIST-TYPE:VOD":
            continue
        updated_lines.append(line)

    with open(subtitle_playlist_path, "w") as f:
        f.writelines(updated_lines)

    logging.info(f"Updated subtitle playlist {subtitle_playlist_path} with version and playlist type VOD.")

def main():
    # --- Argument Parsing Setup ---
    # Step 1: Create a preliminary parser to find the config file path.
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", default="config.json", help="Path to the JSON configuration file.")
    config_args, _ = config_parser.parse_known_args()

    # Step 2: Load the configuration file.
    config = {}
    if os.path.exists(config_args.config):
        try:
            with open(config_args.config, 'r') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            logging.error(f"Error: Could not parse configuration file '{config_args.config}': {e}")
            return
    else:
        logging.warning(f"Configuration file '{config_args.config}' not found. Using hardcoded defaults.")

    # Load defaults from config for use in argument definitions.
    video_templates = config.get("video_templates")
    defaults = config.get("defaults", {})
    paths = config.get("paths", {})
    s3_config = config.get("s3", {})
    esam_config = config.get("Esam", {})
    mediapackage_config = defaults.get("mediapackage", {})

    default_input_video = defaults.get("input_video", "samsung_test_assets/JAN_CarlsCarWash2_Th_en.mp4")
    default_output_dir = defaults.get("output_dir", "hls_output_264_wz")
    default_subtitle_file = defaults.get("subtitle_file", None)
    default_subtitle_language = defaults.get("subtitle_language", "en")
    default_upload = defaults.get("upload", False)
    default_esam = defaults.get("esam", False)
    default_audio_norm = defaults.get("audio_norm", False)
    default_import_to_mediapackage = defaults.get("import", False)

    default_mp_channel_id = mediapackage_config.get("channel_id", "VISIONULAR_AVC_TEST")
    default_mp_region = mediapackage_config.get("region", "us-east-1")
    default_mp_debug_aws = mediapackage_config.get("debug_aws", False)
    default_mp_packaging_group_id = mediapackage_config.get("packaging_group_id", "vod_samsung_test")
    default_mp_vod_role_name = mediapackage_config.get("vod_role_name", "MediaPackage_VOD_Role")
    default_mp_package_type = mediapackage_config.get("package_type", "CMAF")
    default_mp_delete_existing_vod_assets = mediapackage_config.get("delete_existing_vod_assets", False)

    # Step 3: Define the main parser with all arguments.
    parser = argparse.ArgumentParser(
        description="Generate HLS VOD from a video file with optional subtitles and upload to S3."
    )

    parser.add_argument("--config", default=config_args.config, help="Path to the JSON configuration file.")
    parser.add_argument("--input", default=default_input_video, help="Path to the input video file.")
    parser.add_argument("--output", default=default_output_dir, help="Output directory for HLS files.")
    parser.add_argument("--subtitle", default=default_subtitle_file, help="Path to the subtitle (VTT) file. If not provided, subtitles will be omitted.")
    parser.add_argument("--sub-lang", default=default_subtitle_language, help="Language of the subtitle track (e.g., 'en', 'es').")
    parser.add_argument("--upload", action="store_true", help="Upload generated HLS files to S3 after transcoding.")
    parser.add_argument("--esam", action="store_true", help="Inject ESAM markers into the HLS playlist.")
    parser.add_argument("--audio_norm", action="store_true", help="Enable audio normalization using loudnorm.")
    parser.add_argument("--generate-thumbnails", action="store_true", help="Enable thumbnail generation.")
    parser.add_argument("--template", default="h264_standard", help="Name of the video template to use from config.json (e.g., 'h264_standard').")
    parser.add_argument("--packaging-group-id", default=default_mp_packaging_group_id, help="The ID for the MediaPackage VOD Packaging Group.")
    parser.add_argument("--vod-role-name", default=default_mp_vod_role_name, help="The IAM Role name for MediaPackage VOD to access S3.")
    parser.add_argument("--region", default=default_mp_region, help="The AWS region for MediaPackage.")
    parser.add_argument("--package-type", default=default_mp_package_type, choices=["HLS", "CMAF", "ALL"], help="Specify the package type (HLS, CMAF, or ALL) for the VOD Asset.")
    parser.add_argument("--delete-existing-vod-assets", action="store_true", help="Delete and recreate existing MediaPackage VOD assets and configurations.")
    parser.add_argument("--import", dest="import_to_mediapackage", action="store_true", help="Import to MediaPackage from S3 after upload. Requires --upload.")
    parser.add_argument("--debug-aws", action="store_true", help="Enable AWS CLI debug logging for MediaPackage operations.")
    parser.add_argument("--log-file", help="Path to the log file. If not specified, a timestamped file will be created in the current directory.")
    parser.add_argument("--duration", type=int, help="Optional: Limit the processing duration to the first N seconds of the input.")

    # Step 4: Parse all arguments from the command line.
    args = parser.parse_args()

    # Now that args are parsed, we can do final validation.
    if video_templates is None:
        logging.error("Error: 'video_templates' is missing from config.json. Please ensure it is configured.")
        return

    # Setup logging after parsing args and loading config
    setup_logging(args, config)

    # Apply config defaults for boolean flags if not explicitly set on command line
    arg_defaults = {
        'upload': default_upload,
        'esam': default_esam,
        'audio_norm': default_audio_norm,
        'import_to_mediapackage': default_import_to_mediapackage,
        'debug_aws': default_mp_debug_aws,
        'package_type': default_mp_package_type,
        'delete_existing_vod_assets': default_mp_delete_existing_vod_assets,
    }
    for arg_name, default_value in arg_defaults.items():
        if not getattr(args, arg_name, False):
            setattr(args, arg_name, default_value)

    input_video = args.input
    output_dir = os.path.abspath(args.output)
    subtitle_file = args.subtitle

    upload_to_s3 = args.upload
    audio_normalization_enabled = args.audio_norm
    audio_normalization_config = config.get("audio_normalization", {})
    loudnorm_settings = audio_normalization_config.get("loudnorm_settings", {})

    thumbnail_config = config.get("thumbnail_generation", {})
    generate_thumbnails_enabled = args.generate_thumbnails or thumbnail_config.get("enabled", False)
    thumbnail_output_dir = os.path.join(output_dir, thumbnail_config.get("output_dir", "thumbnails"))
    thumbnail_s3_subfolder_name = thumbnail_config.get("s3_subfolder_name", "thumbnails")

    ffmpeg_executable = os.path.abspath(paths.get("ffmpeg_executable", ""))
    ffprobe_executable = os.path.abspath(paths.get("ffprobe_executable", ""))
    s3_base_path = s3_config.get("base_path", "s3://mediapackage-live2vod/mediaconvert/output/")

    # Validate and log input sources
    if is_url(input_video):
        logging.info(f"Processing video from URL: {input_video}")
        if not validate_url(input_video):
            logging.error(f"Error: Cannot access video URL: {input_video}")
            return
    else:
        logging.info(f"Processing video from local file: {input_video}")

    if subtitle_file:
        if is_url(subtitle_file):
            logging.info(f"Processing subtitle from URL: {subtitle_file}")
            if not validate_url(subtitle_file):
                logging.error(f"Error: Cannot access subtitle URL: {subtitle_file}")
                return
        else:
            logging.info(f"Processing subtitle from local file: {subtitle_file}")

    video_fps = get_video_fps(ffprobe_executable, input_video)
    logging.info(f"Detected video FPS: {video_fps}")

    clippings = defaults.get("InputClippings", [])
    if args.duration is not None:
        logging.info(f"Duration argument ({args.duration}s) provided. Ignoring InputClippings configuration.")
        clippings = []
    temp_clipping_dir = None

    # Handle subtitle input path - keep as is if it's a URL, otherwise make absolute
    subtitle_input_path = subtitle_file if subtitle_file else None
    if subtitle_input_path and not is_url(subtitle_input_path):
        subtitle_input_path = os.path.abspath(subtitle_input_path)
    
    ffmpeg_input_path = None

    try:
        events = []
        if args.esam:
            logging.info("Parsing ESAM XML from config...")
            scc_xml = esam_config.get("SignalProcessingNotification", {}).get("SccXml")
            if not scc_xml:
                logging.warning("Warning: ESAM injection requested, but no SccXml found in config.json.")
            else:
                events = parse_esam_xml_string(scc_xml)
                if not events:
                    logging.warning("Warning: No ESAM events parsed from SccXml.")
                else:
                    # Filter ESAM events based on duration if provided
                    if args.duration:
                        original_event_count = len(events)
                        events = [event for event in events if event["npt"] <= args.duration]
                        if len(events) < original_event_count:
                            logging.info(f"Filtered {original_event_count - len(events)} ESAM events outside the specified duration ({args.duration}s).")

        if clippings:
            logging.info("InputClippings detected in config.json. Processing video segments...")
            video_ffconcat, subtitle_ffconcat, temp_clipping_dir = process_clippings(
                input_video, ffmpeg_executable, clippings, video_fps, subtitle_file
            )

            if not video_ffconcat:
                logging.error("Error: Failed to process input clippings. Exiting.")
                return

            ffmpeg_input_path = os.path.abspath(video_ffconcat)
            if subtitle_ffconcat:
                subtitle_input_path = os.path.abspath(subtitle_ffconcat)

        else:
            # Handle URL vs local file for ffmpeg input path
            if is_url(input_video):
                ffmpeg_input_path = input_video
            else:
                ffmpeg_input_path = os.path.abspath(input_video)

        template_name = args.template
        selected_resolutions_data = video_templates.get(template_name)
        if selected_resolutions_data is None:
            logging.error(f"Error: Video template '{template_name}' not found in config.json. Please check your configuration.")
            return

        if not selected_resolutions_data:
            logging.error("Error: No valid resolutions specified. Exiting.")
            return

        # Clear and create output directory
        if os.path.exists(output_dir):
            logging.info(f"Clearing existing output directory: {output_dir}")
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Subtitle Processing
        subtitle_playlist_full_path = None
        if subtitle_input_path:
            if not process_subtitles(ffmpeg_executable, subtitle_input_path, output_dir, args.sub_lang, args.duration):
                logging.error("Subtitle processing failed. Exiting.")
                return
            subtitle_playlist_full_path = os.path.join(output_dir, f"channel_{args.sub_lang}-vtt.m3u8")
            update_subtitle_playlist(subtitle_playlist_full_path)

        loudnorm_analysis_results = {}
        if audio_normalization_enabled:
            logging.info("Running loudnorm analysis...")
            cwd = temp_clipping_dir if temp_clipping_dir else None
            loudnorm_analysis_results = run_loudnorm_analysis(ffmpeg_executable, ffmpeg_input_path, duration=args.duration, cwd=cwd)
            if not loudnorm_analysis_results:
                logging.warning("Warning: Loudnorm analysis failed. Audio normalization will be skipped.")
                audio_normalization_enabled = False
            else:
                logging.info("Loudnorm analysis results:")
                for k, v in loudnorm_analysis_results.items():
                    logging.info(f"  {k}: {v}")

        ffmpeg_cmd = [
            ffmpeg_executable,
            "-y",
            "-thread_queue_size", "1024",
        ]

        if args.duration:
            ffmpeg_cmd.extend(["-t", str(args.duration)])

        if "ffconcat" in os.path.basename(ffmpeg_input_path):
            ffmpeg_cmd.extend(["-safe", "0"])

        ffmpeg_cmd.extend(["-i", ffmpeg_input_path])

        # --- HLS Generation Command ---
        num_resolutions = len(selected_resolutions_data)
        video_split_outputs = [f"[v{i}]" for i in range(num_resolutions)]

        filter_complex_parts = []
        if num_resolutions > 0:
            filter_complex_parts.append(f"[0:v]split={num_resolutions}{''.join(video_split_outputs)}")

        for i, res_data in enumerate(selected_resolutions_data):
            video_filters = f"scale=w={res_data['width']}:h={res_data['height']}"
            if res_data.get("interlace_mode") and res_data["interlace_mode"] == "PROGRESSIVE":
                video_filters = f"yadif=mode=0:parity=auto:deint=1,{video_filters}"
            filter_complex_parts.append(f"[v{i}]{video_filters}[v{i}out]")

        audio_filter_str = ""
        if audio_normalization_enabled and loudnorm_analysis_results:
            target_i = loudnorm_settings.get("i", -23)
            target_lra = loudnorm_settings.get("lra", 7)
            target_tp = loudnorm_settings.get("tp", -2)

            input_i = loudnorm_analysis_results.get("input_i")
            input_tp = loudnorm_analysis_results.get("input_tp")
            input_lra = loudnorm_analysis_results.get("input_lra")

            if input_i is not None and input_tp is not None and input_lra is not None:
                audio_filter_str = (
                    f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:"
                    f"measured_I={input_i}:measured_LRA={input_lra}:"
                    f"measured_TP={input_tp}:print_format=summary"
                )
                filter_complex_parts.append(f"[0:a]{audio_filter_str},asplit={len(selected_resolutions_data)}{''.join([f'[a{i}out]' for i in range(len(selected_resolutions_data))])}")
            else:
                logging.warning("Warning: Loudnorm analysis results are incomplete. Audio normalization will be skipped.")
                filter_complex_parts.append(f"[0:a]asplit={len(selected_resolutions_data)}{''.join([f'[a{i}out]' for i in range(len(selected_resolutions_data))])}")
        else:
            filter_complex_parts.append(f"[0:a]asplit={len(selected_resolutions_data)}{''.join([f'[a{i}out]' for i in range(len(selected_resolutions_data))])}")

        filter_complex_str = "; ".join(filter_complex_parts)

        # Build FFmpeg command for HLS generation
        hls_ffmpeg_cmd = [
            ffmpeg_executable,
            "-y",
            "-thread_queue_size", "1024",
        ]

        if args.duration:
            hls_ffmpeg_cmd.extend(["-t", str(args.duration)])

        if "ffconcat" in os.path.basename(ffmpeg_input_path):
            hls_ffmpeg_cmd.extend(["-safe", "0"])

        hls_ffmpeg_cmd.extend(["-i", ffmpeg_input_path])
        hls_ffmpeg_cmd.extend(["-filter_complex", filter_complex_str])

        for i, res_data in enumerate(selected_resolutions_data):
            hls_ffmpeg_cmd.extend(["-map", f"[v{i}out]", "-map", f"[a{i}out]"])

            codec_name = ""
            codec_params_arg = []
            if res_data.get("codec") == "H_264":
                codec_name = "libx264"
                if res_data.get("codec_params"):
                    codec_params_arg = [f"-x264-params:v:{i}", res_data["codec_params"]]
            elif res_data.get("codec") == "H_265":
                codec_name = "libx265"
                if res_data.get("codec_params"):
                    codec_params_arg = [f"-x265-params:v:{i}", res_data["codec_params"]]
            else:
                logging.warning(f"Unsupported codec '{res_data.get('codec')}' for resolution {res_data['name']}. Defaulting to libx264.")
                codec_name = "libx264"

            gop_size = res_data.get("GopSize", 6)
            gop_size_units = res_data.get("GopSizeUnits", "SECONDS") # Default to SECONDS

            force_key_frames_expr = ""
            if gop_size_units == "SECONDS":
                force_key_frames_expr = f"expr:gte(t,n_forced*{gop_size})"
            elif gop_size_units == "FRAMES":
                force_key_frames_expr = f"expr:if(mod(n,{gop_size}),0,1)"
            else:
                logging.warning(f"Unsupported GopSizeUnits '{gop_size_units}' for resolution {res_data['name']}. Defaulting to SECONDS with GopSize 6.")
                force_key_frames_expr = "expr:gte(t,n_forced*6)"

            hls_ffmpeg_cmd.extend([
                f"-c:v:{i}", codec_name,
            ] + codec_params_arg)

            if res_data.get("codec") == "H_265":
                hls_ffmpeg_cmd.extend([f"-tag:v:{i}", "hvc1"])

            current_preset = res_data.get("preset", "slower")
            hls_ffmpeg_cmd.extend([f"-preset:v:{i}", current_preset])

            if res_data.get('bitrate'):
                hls_ffmpeg_cmd.extend([f"-b:v:{i}", res_data['bitrate']])

            if res_data.get('threads'):
                hls_ffmpeg_cmd.extend([f"-threads:v:{i}", str(res_data['threads'])])

            hls_ffmpeg_cmd.extend([
                f"-force_key_frames:v:{i}", force_key_frames_expr,
                #f"-x264opts:v:{i}", res_data.get("x264opts", "1"),
            ])

            if res_data.get('crf') is not None:
                hls_ffmpeg_cmd.extend([f"-crf:v:{i}", str(res_data['crf'])])

            hls_ffmpeg_cmd.extend([
                f"-c:a:{i}", "aac",
                f"-b:a:{i}", "128k",
            ])

        var_stream_map_entries = [f"v:{i},a:{i},name:{res_data['name']}" for i, res_data in enumerate(selected_resolutions_data)]
        var_stream_map_content = " ".join(var_stream_map_entries)
        hls_ffmpeg_cmd.extend(["-var_stream_map", var_stream_map_content])

        master_playlist_path = os.path.join(output_dir, "channel.m3u8")
        hls_ffmpeg_cmd.extend([
            "-f", "hls",
            "-start_number", "1",
            "-hls_time", "6",
            "-hls_playlist_type", "vod",
            "-master_pl_name", "channel.m3u8",
            "-hls_segment_filename", os.path.join(output_dir, "channel_%v_%05d.ts"),
            "-hls_flags", "independent_segments",
            "-hls_segment_type", "mpegts",
            "-y", os.path.join(output_dir, "channel_%v.m3u8"),
        ])

        hls_ffmpeg_cmd_shell = " ".join(shlex.quote(arg) for arg in hls_ffmpeg_cmd)
        logging.info(f"Executing FFmpeg command for HLS generation. Command: {hls_ffmpeg_cmd_shell}")
        try:
            subprocess.run(hls_ffmpeg_cmd, check=True, text=True, encoding='utf-8', errors='ignore')
            logging.info("HLS generation completed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error during FFmpeg execution for HLS generation: {e}")
            logging.error(f"FFmpeg stderr:\n{e.stderr}")
            return
        except FileNotFoundError:
            logging.error(f"Error: FFmpeg executable '{ffmpeg_executable}' not found. Make sure it exists and is executable.")
            return

        # --- Thumbnail Generation ---
        if generate_thumbnails_enabled:
            os.makedirs(thumbnail_output_dir, exist_ok=True)
            thumbnail_interval = thumbnail_config.get("interval_seconds", 10)
            thumbnail_width = thumbnail_config.get("width", 320)
            thumbnail_height = thumbnail_config.get("height", 180)
            thumbnail_quality = thumbnail_config.get("quality", 80)
            thumbnail_output_format = thumbnail_config.get("output_format", "jpg")

            thumb_ffmpeg_cmd = [
                ffmpeg_executable,
                "-y",
                "-thread_queue_size", "1024", # Use thread_queue_size for thumbnails as well
            ]
            if args.duration:
                thumb_ffmpeg_cmd.extend(["-t", str(args.duration)])

            if "ffconcat" in os.path.basename(ffmpeg_input_path):
                thumb_ffmpeg_cmd.extend(["-safe", "0"])

            thumb_ffmpeg_cmd.extend([
                "-i", ffmpeg_input_path,
                "-vf", f"fps=1/{thumbnail_interval},scale={thumbnail_width}:{thumbnail_height}",
                "-q:v", str(thumbnail_quality),
                os.path.join(thumbnail_output_dir, f"thumb_%04d.{thumbnail_output_format}")
            ])

            thumb_ffmpeg_cmd_shell = " ".join(shlex.quote(arg) for arg in thumb_ffmpeg_cmd)
            logging.info(f"Executing FFmpeg command for thumbnail generation. Command: {thumb_ffmpeg_cmd_shell}")
            try:
                subprocess.run(thumb_ffmpeg_cmd, check=True, text=True, encoding='utf-8', errors='ignore')
                logging.info("Thumbnail generation completed successfully.")
            except subprocess.CalledProcessError as e:
                logging.error(f"Error during FFmpeg execution for thumbnails: {e}")
                logging.error(f"FFmpeg stderr:\n{e.stderr}")
                # Don't return here, HLS might have succeeded
            except FileNotFoundError:
                logging.error(f"Error: FFmpeg executable '{ffmpeg_executable}' not found for thumbnail generation.")

        if subtitle_input_path:
            update_master_playlist_for_subtitles(master_playlist_path, args.sub_lang)

        # ESAM injection, now correctly placed after all playlists are generated
        if args.esam and events:
            logging.info("Injecting ESAM markers into master playlist and variants...")
            process_playlist(master_playlist_path, events)
            if subtitle_playlist_full_path:
                logging.info(f"Injecting ESAM markers into subtitle playlist: {subtitle_playlist_full_path}")
                process_playlist(subtitle_playlist_full_path, events)

        if upload_to_s3:
            output_dir_name = os.path.basename(os.path.normpath(output_dir))
            s3_destination_path = os.path.join(s3_base_path, output_dir_name).replace("\\", "/")

            logging.info(f"\nAttempting to upload HLS files from '{output_dir}' to S3 '{s3_destination_path}'")

            try:
                # Use the centralized run_aws_cli helper for all aws commands
                rm_cmd = ["aws", "s3", "rm", "--recursive", s3_destination_path]
                run_aws_cli(rm_cmd, capture_output=True, check=True) # Use capture_output=False to see progress
                logging.info("Existing S3 content cleared successfully.")

                cp_cmd = ["aws", "s3", "cp", "--recursive", output_dir, s3_destination_path]
                run_aws_cli(cp_cmd, capture_output=True, check=True) # Use capture_output=False to see progress
                logging.info("HLS files uploaded to S3 successfully.")

                # Upload thumbnails to S3 if enabled
                if generate_thumbnails_enabled:
                    logging.info(f"\nAttempting to upload thumbnails from '{thumbnail_output_dir}' to S3 '{s3_destination_path}/{thumbnail_s3_subfolder_name}'")
                    thumbnail_s3_destination = os.path.join(s3_destination_path, thumbnail_s3_subfolder_name).replace("\\", "/")
                    cp_thumbnail_cmd = ["aws", "s3", "cp", "--recursive", thumbnail_output_dir, thumbnail_s3_destination]
                    run_aws_cli(cp_thumbnail_cmd, capture_output=True, check=True) # Use capture_output=False to see progress
                    logging.info("Thumbnails uploaded to S3 successfully.")

            except (RuntimeError, TimeoutError) as e:
                logging.error(f"An error occurred during S3 upload: {e}")
                return

            if args.import_to_mediapackage:
                logging.info("\nAttempting to import HLS content into MediaPackage...")

                parsed_s3_base_path = urllib.parse.urlparse(s3_base_path)
                s3_bucket_name = parsed_s3_base_path.netloc

                parsed_s3_destination_path = urllib.parse.urlparse(s3_destination_path)
                s3_key_for_mediapackage = os.path.join(
                    parsed_s3_destination_path.path.lstrip('/')
                    , "channel.m3u8"
                ).replace("\\", "/")
                s3_source_arn = f"arn:aws:s3:::{s3_bucket_name}/{s3_key_for_mediapackage}"

                aws_account_id = get_aws_account_id(args.region, args.debug_aws)
                if not aws_account_id:
                    logging.error("Could not retrieve AWS account ID. Halting MediaPackage steps.")
                    return

                mediapackage_results = manage_mediapackage_vod_asset(
                    region=args.region,
                    packaging_group_id=args.packaging_group_id,
                    vod_role_arn=f"arn:aws:iam::{aws_account_id}:role/{args.vod_role_name}",
                    s3_source_arn=s3_source_arn,
                    package_type=args.package_type,
                    delete_existing_vod_assets=args.delete_existing_vod_assets,
                    debug=args.debug_aws
                )

                logging.info("MediaPackage integration completed successfully.")

                if mediapackage_results.get("playback_urls"):
                    logging.info("\nDetected MediaPackage Playback URLs:")
                    for url in mediapackage_results['playback_urls']:
                        logging.info(f"- {url}")
                else:
                    logging.info("\nNo specific MediaPackage Playback URLs detected in the output.")
    finally:
        if temp_clipping_dir:
            logging.info(f"Cleaning up temporary clipping directory: {temp_clipping_dir}")
            shutil.rmtree(temp_clipping_dir)

def get_aws_account_id(region, debug=False):
    aws_cmd_prefix = ["aws"]
    if debug:
        aws_cmd_prefix.append("--debug")
    try:
        account_id = subprocess.run(
            aws_cmd_prefix + ["sts", "get-caller-identity", "--query", "Account", "--output", "text", "--region", region],
            check=True, capture_output=True, text=True
        ).stdout.strip()
        return account_id
    except subprocess.CalledProcessError as e:
        logging.error(f"Error retrieving AWS account ID: {e.stderr.decode(errors='ignore')}")
        return None
    except FileNotFoundError:
        logging.error("Error: AWS CLI not found. Please install and configure AWS CLI to use AWS operations.")
        return None


def parse_esam_xml_string(xml_string):
    ns = {
        "esam": "urn:cablelabs:iptvservices:esam:xsd:signal:1",
        "sig": "urn:cablelabs:md:xsd:signaling:3.0",
        "common": "urn:cablelabs:iptvservices:esam:xsd:common:1",
    }
    root = ET.fromstring(xml_string)
    events = []
    for rs in root.findall(".//esam:ResponseSignal", ns):
        point = rs.find("sig:NPTPoint", ns)
        seginfo = rs.find("sig:SCTE35PointDescriptor/sig:SegmentationDescriptorInfo", ns)
        if point is None:
            continue
        try:
            npt = float(point.get("nptPoint"))
        except (ValueError, TypeError):
            continue
        ev = {
            "npt": npt,
            "duration": None,
            "segmentTypeId": None,
            "segmentEventId": None,
        }
        if seginfo is not None:
            dur = seginfo.get("duration") or seginfo.get("Duration")
            if dur and dur.startswith("PT") and dur.endswith("S"):
                try:
                    ev["duration"] = float(dur[2:-1])
                except ValueError:
                    ev["duration"] = None
            ev["segmentTypeId"] = seginfo.get("segmentTypeId")
            ev["segmentEventId"] = seginfo.get("segmentEventId")
        events.append(ev)
    events.sort(key=lambda x: x["npt"])
    logging.info(f"Parsed {len(events)} ESAM event(s) from XML string")
    return events

def is_master_playlist(lines):
    for ln in lines:
        if ln.strip().startswith("#EXT-X-STREAM-INF"):
            return True
    return False

def find_variants(lines, basepath: Path):
    variants = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("#EXT-X-STREAM-INF"):
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                uri = lines[j].strip()
                variants.append((uri, (basepath / uri).resolve()))
            i = j
        else:
            i += 1
    return variants

def parse_variant_segments(m3u8_path: Path):
    text = m3u8_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    segments = []  # (start, end, filename, filename_line_index)
    total = 0.0
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("#EXTINF:"):
            try:
                dur = float(ln.split(":",1)[1].split(",",1)[0])
            except:
                dur = 0.0
            if i + 1 < len(lines):
                segfile = lines[i+1].strip()
                segments.append((total, total + dur, segfile, i+1))
            total += dur
            i += 2
        else:
            i += 1
    return lines, segments, total

def has_marker_near(lines, insert_index, prefixes):
    start = max(0, insert_index - 3)
    end = min(len(lines), insert_index + 2)
    for k in range(start, end):
        ln = lines[k].strip()
        for p in prefixes:
            if ln.startswith(p):
                return True
    return False

def inject_elemental_markers(m3u8_path: Path, esam_events):
    lines, segments, total = parse_variant_segments(m3u8_path)
    if not segments:
        logging.info(f"{m3u8_path.name}: No segments found, skipping")
        return 0

    plans = []
    for ev in esam_events:
        npt = ev["npt"]
        matched = False
        for idx, (sstart, send, sfile, sline) in enumerate(segments):
            if sstart <= npt < send:
                plans.append((idx, ev))
                matched = True
                break
        if not matched and npt <= total:
            plans.append((len(segments)-1, ev))
        elif npt > total:
            logging.info(f"{m3u8_path.name}: Skipping signal {npt:.2f}s (out of playlist duration {total:.2f}s)")

    if not plans:
        return 0

    # Insert from back to front to avoid index errors
    plans.sort(key=lambda x: x[0], reverse=True)

    inserted_count = 0
    for idx, ev in plans:
        sstart, send, sfile, sline = segments[idx]
        insert_pos = sline

        # Avoid duplicates
        if has_marker_near(lines, insert_pos, ["#EXT-X-CUE-OUT", "#EXT-X-CUE-OUT-CONT", "#EXT-X-CUE-IN"]):
            logging.info(f"{m3u8_path.name}: Marker already exists, skipping {sfile}")
            continue

        stype = ev.get("segmentTypeId")
        duration = ev.get("duration") or 30.0

        # If it's an end signal (53) -> insert CUE-IN
        if stype == "53":
            lines.insert(insert_pos, "#EXT-X-CUE-IN\n")
            inserted_count += 1
            logging.info(f"{m3u8_path.name}: Inserting EXT-X-CUE-IN before {sfile} (signal {ev['npt']:.2f}s)")
            continue

        # Otherwise, treat as a start (cue-out)
        cueout_tag = f"#EXT-X-CUE-OUT:{duration:.3f}\n"
        lines.insert(insert_pos, cueout_tag)
        inserted_count += 1
        logging.info(f"{m3u8_path.name}: Inserting EXT-X-CUE-OUT (duration={duration}) before {sfile} (signal {ev['npt']:.2f}s)")

        # For subsequent segments, insert EXT-X-CUE-OUT-CONT:Elapsed/Duration format until elapsed >= duration
        j = idx + 1
        while j < len(segments):
            seg_start, seg_end, seg_file, seg_line = segments[j]
            elapsed = seg_start - sstart
            if elapsed >= duration:
                # Insert CUE-IN before this segment and end
                if not has_marker_near(lines, seg_line, ["#EXT-X-CUE-IN"]):
                    lines.insert(seg_line, "#EXT-X-CUE-IN\n")
                    inserted_count += 1
                    logging.info(f"{m3u8_path.name}: Inserting EXT-X-CUE-IN before {seg_file} (elapsed {elapsed:.3f}s)")
                break

            cont_tag = f"#EXT-X-CUE-OUT-CONT:{elapsed:.3f}/{int(duration)}\n"
            if not has_marker_near(lines, seg_line, ["#EXT-X-CUE-OUT-CONT"]):
                lines.insert(seg_line, cont_tag)
                inserted_count += 1
                logging.info(f"{m3u8_path.name}: Inserting EXT-X-CUE-OUT-CONT before {seg_file} (elapsed {elapsed:.3f}s)")
            j += 1
        else:
            # If the ad hasn't finished by the end of the playlist, insert CUE-IN at the end as a policy
            last_line = segments[-1][3]
            if not has_marker_near(lines, last_line+1, ["#EXT-X-CUE-IN"]):
                lines.insert(last_line+1, "#EXT-X-CUE-IN\n")
                inserted_count += 1
                logging.info(f"{m3u8_path.name}: Inserting EXT-X-CUE-IN at the end of the playlist (ad ran to end)")

    # Write back to file
    m3u8_path.write_text("".join(lines), encoding="utf-8")
    return inserted_count

def process_playlist(m3u8_arg: str, esam_events):
    m3u8_path = Path(m3u8_arg).resolve()
    if not m3u8_path.exists():
        logging.error(f"Playlist not found: {m3u8_path}")
        return
    content = m3u8_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if is_master_playlist(content):
        variants = find_variants(content, m3u8_path.parent)
        logging.info(f"Master playlist detected, variant count: {len(variants)}")
        total = 0
        for uri, abs_path in variants:
            if not abs_path.exists():
                logging.warning(f"Variant file not found, skipping: {uri} -> {abs_path}")
                continue
            logging.info(f"Processing variant: {uri}")
            cnt = inject_elemental_markers(abs_path, esam_events)
            logging.info(f"  Injected {cnt} markers into {uri}")
            total += cnt
        logging.info(f"Total injected markers across all variants: {total}")
    else:
        cnt = inject_elemental_markers(m3u8_path, esam_events)
        logging.info(f"Injected {cnt} markers into {m3u8_path.name}")

def run_aws_cli(cmd_list, capture_output=True, text=True, check=True):
    """Run AWS CLI command safely and return stdout."""
    try:
        result = subprocess.run(cmd_list, capture_output=capture_output, text=text, check=check)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
        raise RuntimeError(err)
    except FileNotFoundError:
        raise RuntimeError("AWS CLI not found. Please install AWS CLI.")

def wait_until(fn, timeout=600, interval=5, description="resource"):
    """Poll a function until it returns True or timeout."""
    start = time.time()
    while True:
        if fn():
            return True
        if time.time() - start > timeout:
            raise TimeoutError(f"Timeout waiting for {description}")
        time.sleep(interval)

def manage_mediapackage_vod_asset(region, packaging_group_id, vod_role_arn, s3_source_arn,
                                  package_type="ALL", delete_existing_vod_assets=False,
                                  debug=False, polling_timeout_seconds=600):
    """
    Optimized MediaPackage VOD manager using AWS CLI.
    Supports HLS, CMAF, Asset creation and deletion with polling.
    """
    logging.info(f"Managing MediaPackage VOD Asset in region: {region}")

    aws_cmd = ["aws"]
    if debug:
        aws_cmd.append("--debug")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    asset_id = f"{packaging_group_id}_ASSET_{timestamp}"

    # --- Resource configuration dictionary ---
    resources = {
        "HLS": {
            "config_id": f"{packaging_group_id}_HLS",
            "package_json": json.dumps({
                "HlsManifests": [{"ManifestName": "index", "AdMarkers": "PASSTHROUGH",
                                  "StreamSelection": {"MinVideoBitsPerSecond": 0,
                                                      "MaxVideoBitsPerSecond": 2147483647,
                                                      "StreamOrder": "ORIGINAL"}}],
                "SegmentDurationSeconds": 6,
                "UseAudioRenditionGroup": False
            }),
            "type_flag": "HLS"
        },
        "CMAF": {
            "config_id": f"{packaging_group_id}_CMAF",
            "package_json": json.dumps({
                "HlsManifests": [{"ManifestName": "index-cmaf", "AdMarkers": "PASSTHROUGH",
                                  "StreamSelection": {"MinVideoBitsPerSecond": 0,
                                                      "MaxVideoBitsPerSecond": 2147483647,
                                                      "StreamOrder": "ORIGINAL"}}],
                "SegmentDurationSeconds": 6
            }),
            "type_flag": "CMAF"
        },
        "Asset": {
            "asset_id": asset_id,
            "source_arn": s3_source_arn,
            "role_arn": vod_role_arn
        }
    }

    # --- Check AWS CLI ---
    try:
        run_aws_cli(aws_cmd + ["--version"])
    except RuntimeError as e:
        logging.error(str(e))
        return {"error": "aws_cli_not_found", "details": str(e)}

    # --- Helper functions ---
    def resource_exists(cmd_list):
        try:
            run_aws_cli(cmd_list)
            return True
        except RuntimeError:
            return False

    def delete_resource(cmd_list, describe_cmd, description):
        try:
            run_aws_cli(cmd_list)
            wait_until(lambda: not resource_exists(describe_cmd),
                       timeout=polling_timeout_seconds, interval=5, description=description)
            logging.info(f"{description} deleted successfully.")
        except RuntimeError as e:
            logging.warning(f"Could not delete {description}: {str(e)}")
        except TimeoutError as e:
            logging.warning(str(e))

    # --- 1. Create or confirm Packaging Group ---
    describe_pg = aws_cmd + ["mediapackage-vod", "describe-packaging-group",
                             "--id", packaging_group_id, "--region", region]
    if not resource_exists(describe_pg):
        logging.info(f"Creating Packaging Group {packaging_group_id}...")
        create_pg = aws_cmd + ["mediapackage-vod", "create-packaging-group",
                               "--id", packaging_group_id, "--region", region]
        try:
            run_aws_cli(create_pg)
            logging.info(f"Packaging Group {packaging_group_id} created.")
        except RuntimeError as e:
            logging.error(str(e))
            return {"error": "create_pg_failed", "details": str(e)}
    else:
        logging.info(f"Packaging Group {packaging_group_id} exists.")

    # --- 2. Handle HLS/CMAF configs ---
    for key, cfg in resources.items():
        if key in ["HLS", "CMAF"]:
            if package_type not in [key, "ALL"]:
                continue
            describe_cmd = aws_cmd + ["mediapackage-vod", "describe-packaging-configuration",
                                      "--id", cfg["config_id"], "--region", region]
            delete_cmd = aws_cmd + ["mediapackage-vod", "delete-packaging-configuration",
                                    "--id", cfg["config_id"], "--region", region]
            if delete_existing_vod_assets:
                delete_resource(delete_cmd, describe_cmd, f"{key} config")

            if not resource_exists(describe_cmd):
                logging.info(f"Creating {key} Packaging Configuration {cfg['config_id']}...")
                create_cmd = aws_cmd + ["mediapackage-vod", "create-packaging-configuration",
                                        "--id", cfg["config_id"],
                                        "--packaging-group-id", packaging_group_id,
                                        f"--{cfg['type_flag'].lower()}-package", cfg["package_json"],
                                        "--region", region]
                try:
                    run_aws_cli(create_cmd)
                    logging.info(f"{key} Packaging Configuration {cfg['config_id']} created.")
                except RuntimeError as e:
                    logging.error(f"Failed to create {key} config: {str(e)}")
                    return {"error": f"{key.lower()}_config_create_failed", "details": str(e)}

    # --- 3. Handle Asset ---
    describe_asset_cmd = aws_cmd + ["mediapackage-vod", "describe-asset", "--id", asset_id, "--region", region]
    delete_asset_cmd = aws_cmd + ["mediapackage-vod", "delete-asset", "--id", asset_id, "--region", region]

    if delete_existing_vod_assets and resource_exists(describe_asset_cmd):
        delete_resource(delete_asset_cmd, describe_asset_cmd, "Asset")

    logging.info(f"Creating Asset {asset_id} from S3 {s3_source_arn}...")
    create_asset_cmd = aws_cmd + ["mediapackage-vod", "create-asset",
                                  "--id", asset_id,
                                  "--packaging-group-id", packaging_group_id,
                                  "--source-arn", s3_source_arn,
                                  "--source-role-arn", vod_role_arn,
                                  "--region", region]
    try:
        run_aws_cli(create_asset_cmd)
    except RuntimeError as e:
        logging.error(str(e))
        return {"error": "create_asset_failed", "details": str(e)}

    # --- 4. Poll Asset until PLAYABLE ---
    def asset_playable():
        try:
            desc = run_aws_cli(describe_asset_cmd + ["--output", "json"])
            endpoints = json.loads(desc).get("EgressEndpoints", [])
            if not endpoints:
                return False
            statuses = [ep.get("Status") for ep in endpoints]
            if any(s == "FAILED" for s in statuses):
                raise RuntimeError("Asset packaging failed.")
            return all(s == "PLAYABLE" for s in statuses)
        except Exception:
            return False

    try:
        wait_until(asset_playable, timeout=polling_timeout_seconds, interval=15, description="Asset PLAYABLE")
        logging.info("Asset is now PLAYABLE.")
    except TimeoutError as e:
        logging.error(str(e))
        return {"error": "asset_not_playable", "details": str(e)}
    except RuntimeError as e:
        logging.error(str(e))
        return {"error": "asset_failed", "details": str(e)}

    # --- 5. Get playback URLs ---
    try:
        desc = run_aws_cli(describe_asset_cmd + ["--output", "json"])
        endpoints = json.loads(desc).get("EgressEndpoints", [])
        playback_urls = [ep.get("Url") for ep in endpoints]
        return {"playback_urls": playback_urls}
    except Exception as e:
        logging.error(f"Failed to get playback URLs: {str(e)}")
        return {"error": "get_playback_urls_failed", "details": str(e)}

if __name__ == "__main__":
    main()

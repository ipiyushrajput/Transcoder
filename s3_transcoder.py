from flask import Flask, request, jsonify
from flask_cors import CORS
import subprocess
import os
import uuid 
import boto3
from botocore.exceptions import ClientError
import tempfile
import shutil
import time
import datetime
from typing import List
from concurrent.futures import ThreadPoolExecutor
import logging
from pydantic import BaseModel, ValidationError
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import glob
import requests
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
CORS(app)

processes = {}
process_termination_flags = {}
process_cleanup_locks = {}
executor = ThreadPoolExecutor(max_workers=10)

S3_BUCKET_NAME = "dev-us-west-2-dvr-bucket" 
s3_client = boto3.client('s3')

# CloudFront distribution domain - you can change this if needed
CLOUDFRONT_DOMAIN = "https://d1qihwu07jtic5.cloudfront.net"

def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')

    log_filename = f"logs/transcoder.log"

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        handler.close()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(process)d] - %(message)s",
        handlers=[
            RotatingFileHandler(
                log_filename,
                maxBytes=50*1024*1024,
                backupCount=50,
            ),
            logging.StreamHandler()
        ]
    )    
setup_logging()

# Input validation schema
class Variant(BaseModel):
    width: int
    height: int
    videoCodec: str
    videoBitrate: int
    framerate: str
    gop: int
    reference_frame: int
    profile: str
    level: str
    audioCodec: str
    audioBitrate: int
    sampleRate: int

class TranscodingRequest(BaseModel):
    inputFile: str
    preset: str
    outputDir: str # This will be the S3 folder name
    variants: List[Variant]
    hls_segment_size: str
    master_filename: str
    hls_playlist_type: str
    hls_flags: str = None
    hls_list_size: str = None

def validate_input_url(url):
    """Validate input URL before starting transcoding"""
    try:
        # For HTTP/HTTPS URLs
        if url.startswith(('http://', 'https://')):
            response = requests.head(url, timeout=10, allow_redirects=True)
            if response.status_code == 403:
                return False, "Input URL returned 403 Forbidden - Access denied"
            elif response.status_code == 404:
                return False, "Input URL returned 404 Not Found - File does not exist"
            elif response.status_code >= 400:
                return False, f"Input URL returned error {response.status_code}"
            return True, "URL is accessible"
        
        # For local files
        elif os.path.exists(url):
            if os.access(url, os.R_OK):
                return True, "Local file is accessible"
            else:
                return False, "Local file is not readable - Permission denied"
        else:
            return False, "Local file does not exist"
            
    except requests.exceptions.RequestException as e:
        return False, f"Error accessing input URL: {str(e)}"
    except Exception as e:
        return False, f"Error validating input: {str(e)}"

def generate_playback_url(output_dir, master_filename):
    """Generate CloudFront playback URL for HLS stream"""
    # Format: https://d1qihwu07jtic5.cloudfront.net/{output_dir}/{output_dir}/master.m3u8
    playback_url = f"{CLOUDFRONT_DOMAIN}/{output_dir}/{output_dir}/{master_filename}.m3u8"
    return playback_url

class S3UploadHandler(FileSystemEventHandler):
    def __init__(self, s3_prefix, temp_dir):
        self.s3_prefix = s3_prefix
        self.temp_dir = temp_dir
        self.uploaded_files = set()
        self.upload_lock = threading.Lock()
        self.should_stop = False
    
    def should_upload_file(self, file_path):
        """Check if a file should be uploaded (ignore temporary files)"""
        if self.should_stop:
            return False
            
        # Ignore temporary files
        if file_path.endswith('.tmp') or '.tmp.' in file_path:
            return False
        
        # Only upload HLS segments and playlists
        if file_path.endswith(('.ts', '.m3u8', '.mp4', '.m4s')):
            return True
            
        return False
    
    def upload_file_with_retry(self, file_path, max_retries=3, delay=1):
        """Upload a file with retry mechanism"""
        if self.should_stop:
            return False
            
        for attempt in range(max_retries):
            try:
                if not os.path.exists(file_path):
                    if attempt == max_retries - 1: # Last attempt
                        logging.warning(f"File not found after {max_retries} attempts: {file_path}")
                    time.sleep(delay)
                    continue
                
                # Calculate relative path for S3 key
                relative_path = os.path.relpath(file_path, self.temp_dir)
                s3_key = f"{self.s3_prefix}/{relative_path}".replace("\\", "/")
                
                # Upload to S3
                s3_client.upload_file(file_path, S3_BUCKET_NAME, s3_key)
                
                with self.upload_lock:
                    self.uploaded_files.add(file_path)
                
                logging.info(f"Uploaded to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
                return True
                
            except Exception as e:
                if attempt == max_retries - 1: # Last attempt
                    logging.error(f"Failed to upload {file_path} to S3 after {max_retries} attempts: {str(e)}")
                else:
                    logging.warning(f"Attempt {attempt + 1} failed for {file_path}: {str(e)}")
                    time.sleep(delay)
        
        return False
    
    def stop_uploading(self):
        """Stop all uploading activities"""
        self.should_stop = True
    
    def on_created(self, event):
        if not event.is_directory and self.should_upload_file(event.src_path):
            # For TS segments, upload immediately
            if event.src_path.endswith('.ts'):
                self.upload_file_with_retry(event.src_path)
    
    def on_modified(self, event):
        if not event.is_directory and self.should_upload_file(event.src_path):
            # For manifest files, wait a bit to ensure they're stable
            if event.src_path.endswith('.m3u8'):
                time.sleep(0.5) # Wait for file to be completely written
                self.upload_file_with_retry(event.src_path, max_retries=5, delay=0.5)
    
    def on_moved(self, event):
        # Handle file renames (FFmpeg might create temp files and then rename them)
        if not event.is_directory and self.should_upload_file(event.dest_path):
            time.sleep(0.2) # Small delay
            self.upload_file_with_retry(event.dest_path, max_retries=3, delay=0.5)

def start_file_watcher(temp_dir, s3_prefix):
    """Start watching a directory for new files and upload them to S3"""
    event_handler = S3UploadHandler(s3_prefix, temp_dir)
    observer = Observer()
    observer.schedule(event_handler, temp_dir, recursive=True)
    observer.start()
    return observer, event_handler

def start_periodic_uploader(temp_dir, s3_prefix, stop_event):
    """Start a background thread that periodically scans and uploads files"""
    def upload_worker():
        upload_handler = S3UploadHandler(s3_prefix, temp_dir)
        while not stop_event.is_set():
            try:
                # Scan for all HLS files and upload them
                for pattern in ['**/*.ts', '**/*.m3u8']:
                    for file_path in glob.glob(os.path.join(temp_dir, pattern), recursive=True):
                        if upload_handler.should_upload_file(file_path) and not stop_event.is_set():
                            # Check if file hasn't been uploaded yet
                            if file_path not in upload_handler.uploaded_files:
                                upload_handler.upload_file_with_retry(file_path)
                
                time.sleep(2) # Scan every 2 seconds
            except Exception as e:
                if not stop_event.is_set():
                    logging.error(f"Error in periodic uploader: {str(e)}")
                    time.sleep(5)
    
    thread = threading.Thread(target=upload_worker, daemon=True)
    thread.start()
    return thread

def build_ffmpeg_command(input_file, preset, output_dir, variants, segment_size, master_filename, 
                        hls_playlist_type=None, hls_flags=None, hls_list_size=None):
    filter_complex = []
    var_stream_map = []
    map_commands = []
    
    # Create a temporary local directory for FFmpeg output
    temp_dir = tempfile.mkdtemp()
    full_output_dir = os.path.join(temp_dir, output_dir)
    os.makedirs(full_output_dir, exist_ok=True)

    for idx, variant in enumerate(variants):
        video_filter = f"[0:v]scale=w={variant.width}:h={variant.height}[v{idx}]"
        filter_complex.append(video_filter)
        map_commands.extend([
            f"-map [v{idx}] -c:v:{idx} {variant.videoCodec} -b:v:{idx} {variant.videoBitrate}",
            f"-r {variant.framerate} -g {variant.gop} -refs {variant.reference_frame}",
            f"-profile:v {variant.profile} -level {variant.level}",
            f"-map a:0 -c:a:{idx} {variant.audioCodec} -b:a:{idx} {variant.audioBitrate} -ar {variant.sampleRate}"
        ])
        var_stream_map.append(f"v:{idx},a:{idx}")

    filter_complex_command = ";".join(filter_complex)
    var_stream_map_command = " ".join(var_stream_map)

    # Build the full ffmpeg command
    ffmpeg_command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-stream_loop", "-1",
        "-i", input_file,
        "-filter_complex", filter_complex_command,
        *(" ".join(map_commands)).split(),
        "-hls_time", segment_size,
        "-pix_fmt", "yuv420p",
        "-preset", preset,
        "-start_number", "1",
        "-hls_segment_filename", os.path.join(full_output_dir, f"segment%v_%04d.ts"),
        "-master_pl_name", f"{master_filename}.m3u8",
        "-var_stream_map", var_stream_map_command,
        "-force_key_frames", f"expr:gte(t,n_forced*{segment_size})",
        os.path.join(full_output_dir, "%v.m3u8")
    ]

    if hls_playlist_type:
        ffmpeg_command.insert(-1, "-hls_playlist_type")
        ffmpeg_command.insert(-1, hls_playlist_type)
    if hls_list_size:
        ffmpeg_command.insert(-1, "-hls_list_size")
        ffmpeg_command.insert(-1, hls_list_size)
    if hls_flags:
        ffmpeg_command.insert(-1, "-hls_flags")
        ffmpeg_command.insert(-1, hls_flags)

    logging.info(f"Generated FFMpeg Command: {' '.join(ffmpeg_command)}")
    return ffmpeg_command, temp_dir

@app.route('/transcoder/start', methods=['POST'])
def start_transcoding():
    try:
        # Parse and validate input
        config = TranscodingRequest(**request.json)

        # Validate input URL before starting transcoding
        is_valid, message = validate_input_url(config.inputFile)
        if not is_valid:
            logging.error(f"[Input URL validation failed: {message}")
            return jsonify({
                "message": "Transcoding failed - Input validation error", 
                "error": message
            }), 400

        # Build FFmpeg command and get temp directory
        ffmpeg_command, temp_dir = build_ffmpeg_command(
            config.inputFile,
            config.preset,
            config.outputDir, # This will be used as S3 folder prefix
            config.variants,
            config.hls_segment_size,
            config.master_filename,
            config.hls_playlist_type,
            config.hls_flags,
            config.hls_list_size
        )
    
        process_id = str(uuid.uuid4())
        stderr_log_file_path = f"ffmpeg_{process_id}.log"
        
        channel_name = config.outputDir
        
        # Generate playback URL
        playback_url = generate_playback_url(config.outputDir, config.master_filename)
        
        # Start file watcher for real-time S3 upload
        observer, event_handler = start_file_watcher(temp_dir, config.outputDir)
        
        # Start periodic uploader as a backup
        stop_event = threading.Event()
        upload_thread = start_periodic_uploader(temp_dir, config.outputDir, stop_event)
        
        with open(stderr_log_file_path, 'a') as stderr_log_file:
            process = subprocess.Popen(ffmpeg_command, stderr=stderr_log_file)
        
        # Create a cleanup lock for this process
        process_cleanup_locks[process_id] = threading.Lock()
        
        processes[process_id] = {
            'process': process,
            'temp_dir': temp_dir,
            's3_prefix': config.outputDir,
            'observer': observer,
            'event_handler': event_handler,
            'stop_event': stop_event,
            'upload_thread': upload_thread,
            'log_file': stderr_log_file_path,
            'playback_url': playback_url # Store playback URL for reference
        }
    
        executor.submit(monitor_process, process_id)
        logging.info(f"[{channel_name}] Started transcoding for process {process_id}. Output will be uploaded to s3://{S3_BUCKET_NAME}/{config.outputDir}")
        logging.info(f"[{channel_name}] Playback URL: {playback_url}")
        
        return jsonify({
            "message": "Transcoding started successfully", 
            "process_id": process_id,
            "input_validation": "Input URL is valid and accessible",
            "playback_url": playback_url
        }), 200

    except ValidationError as e:
        logging.error(f"[{channel_name}] Validation error: {e}")
        return jsonify({"message": "Invalid input", "errors": e.errors()}), 400
    except Exception as e:
        logging.error(f"[{channel_name}] Failed to start transcoding: {str(e)}")
        return jsonify({"message": "Error starting transcoding"}), 500

@app.route('/transcoder/stop', methods=['POST'])
def stop_transcoding():
    data = request.json
    process_id = data.get("process_id")

    if not process_id or process_id not in processes:
        return jsonify({"message": "Invalid process ID"}), 400
    
    # Get the cleanup lock for this process to prevent race conditions
    cleanup_lock = process_cleanup_locks.get(process_id)
    if not cleanup_lock:
        return jsonify({"message": "Process cleanup lock not found"}), 400
    
    with cleanup_lock:
        # Check again if process exists after acquiring lock
        if process_id not in processes:
            return jsonify({"message": "Process already stopped"}), 400
        
        process_info = processes[process_id]
        process = process_info['process']
        channel_name = process_info.get('s3_prefix', 'unknown')
        
        # Set termination flags first
        process_termination_flags[process_id] = True
        
        # Stop the periodic uploader
        if 'stop_event' in process_info:
            process_info['stop_event'].set()
        
        # Stop the file watcher event handler
        if 'event_handler' in process_info:
            process_info['event_handler'].stop_uploading()
        
        # Stop the file watcher observer
        if 'observer' in process_info:
            try:
                if process_info['observer'].is_alive():
                    process_info['observer'].stop()
                    process_info['observer'].join(timeout=5)
            except Exception as e:
                logging.warning(f"[{channel_name}] Error stopping observer for process {process_id}: {str(e)}")
        
        # Terminate the FFmpeg process
        stopped_successfully = False
        try:
            process.terminate()
            # Wait for process to terminate with timeout
            process.wait(timeout=10)
            stopped_successfully = True
            logging.info(f"[{channel_name}] FFmpeg process {process_id} terminated successfully")
        except subprocess.TimeoutExpired:
            try:
                process.kill() # Force kill if terminate doesn't work
                process.wait()
                stopped_successfully = True
                logging.warning(f"[{channel_name}] FFmpeg process {process_id} had to be forcefully killed")
            except Exception as e:
                stopped_successfully = False
                logging.error(f"[{channel_name}] Error killing process {process_id}: {str(e)}")
        except Exception as e:
            stopped_successfully = False
            logging.error(f"[{channel_name}] Error terminating process {process_id}: {str(e)}")
        
        # Do a final upload of all remaining files if needed
        if stopped_successfully:
            try:
                upload_all_remaining_files(process_info['temp_dir'], process_info['s3_prefix'])
            except Exception as e:
                logging.error(f"[{channel_name}] Error during final upload for process {process_id}: {str(e)}")
        
        # Clean up temporary directory
        if os.path.exists(process_info['temp_dir']):
            try:
                shutil.rmtree(process_info['temp_dir'])
                logging.info(f"[{channel_name}] Cleaned up temp directory for process {process_id}")
            except Exception as e:
                logging.error(f"[{channel_name}] Error cleaning temp directory for process {process_id}: {str(e)}")
        
        # Clean up log file
        if os.path.exists(process_info['log_file']):
            try:
                os.remove(process_info['log_file'])
                logging.info(f"[{channel_name}] Cleaned up log file for process {process_id}")
            except Exception as e:
                logging.error(f"[{channel_name}] Error cleaning log file for process {process_id}: {str(e)}")
        
        # Remove from tracking dictionaries
        processes.pop(process_id, None)
        process_termination_flags.pop(process_id, None)
        process_cleanup_locks.pop(process_id, None)
    
    if stopped_successfully:
        logging.info(f"[{channel_name}] Stopped process {process_id} successfully.")
        return jsonify({"message": f"Transcoding stopped successfully for process {process_id}"}), 200
    else:
        logging.warning(f"[{channel_name}] Process {process_id} was not stopped cleanly.")
        return jsonify({"message": f"Transcoding force-stopped for process {process_id}"}), 200

@app.route('/transcoder/status', methods=['GET'])
def status():
    active_processes = list(processes.keys())
    # Include playback URLs in status response
    process_details = {}
    for pid in active_processes:
        if pid in processes:
            process_details[pid] = {
                's3_prefix': processes[pid].get('s3_prefix', 'unknown'),
                'playback_url': processes[pid].get('playback_url', 'N/A')
            }
    return jsonify({
        "active_processes": active_processes, 
        "process_details": process_details
    }), 200

def upload_all_remaining_files(local_dir, s3_prefix):
    """Upload all remaining files in the directory to S3"""
    upload_handler = S3UploadHandler(s3_prefix, local_dir)
    
    for pattern in ['**/*.ts', '**/*.m3u8']:
        for file_path in glob.glob(os.path.join(local_dir, pattern), recursive=True):
            if upload_handler.should_upload_file(file_path):
                upload_handler.upload_file_with_retry(file_path, max_retries=5, delay=1)

def monitor_process(process_id):
    """Monitor the FFmpeg process and handle cleanup when it completes"""
    process_info = processes.get(process_id)
    if not process_info:
        return
    
    process = process_info['process']
    channel_name = process_info.get('s3_prefix', 'unknown')
    
    try:
        process.wait()
    except Exception as e:
        logging.error(f"[{channel_name}] Error waiting for process {process_id}: {str(e)}")
        return

    # Check if process was already cleaned up by stop endpoint
    if process_id not in processes:
        return
        
    # Get the cleanup lock for this process
    cleanup_lock = process_cleanup_locks.get(process_id)
    if not cleanup_lock:
        return
        
    with cleanup_lock:
        # Check again if process exists after acquiring lock
        if process_id not in processes:
            return
            
        # Check if process was terminated by user
        user_terminated = process_termination_flags.get(process_id, False)
        
        if process.poll() is not None:
            # Read the log file for error messages
            error_message = ""
            if os.path.exists(process_info['log_file']):
                try:
                    with open(process_info['log_file'], 'r') as log_file:
                        error_message = log_file.read()
                except Exception as e:
                    error_message = f"Error reading log file: {str(e)}"

            if user_terminated:
                status_message = f"[{channel_name}] Transcoding stopped by user for process {process_id}"
                # Cleanup already done by stop endpoint
            elif process.returncode == 0:
                status_message = f"[{channel_name}] Transcoding completed successfully for process {process_id}"
                
                # Upload any remaining files for successful completion
                if not user_terminated:
                    try:
                        upload_all_remaining_files(process_info['temp_dir'], process_info['s3_prefix'])
                    except Exception as e:
                        logging.error(f"[{channel_name}] Error uploading remaining files for process {process_id}: {str(e)}")
                
                # Clean up temporary directory
                if os.path.exists(process_info['temp_dir']):
                    try:
                        shutil.rmtree(process_info['temp_dir'])
                    except Exception as e:
                        logging.error(f"[{channel_name}] Error cleaning temp directory for process {process_id}: {str(e)}")
                
                # Clean up log file
                if os.path.exists(process_info['log_file']):
                    try:
                        os.remove(process_info['log_file'])
                    except Exception as e:
                        logging.error(f"[{channel_name}] Error cleaning log file for process {process_id}: {str(e)}")
            else:
                status_message = f"[{channel_name}] Transcoding failed with error for process {process_id}: {error_message}"
                # Clean up temporary files on failure
                if os.path.exists(process_info['temp_dir']):
                    try:
                        shutil.rmtree(process_info['temp_dir'])
                    except Exception as e:
                        logging.error(f"[{channel_name}] Error cleaning temp directory for process {process_id}: {str(e)}")
                
                # Clean up log file
                if os.path.exists(process_info['log_file']):
                    try:
                        os.remove(process_info['log_file'])
                    except Exception as e:
                        logging.error(f"[{channel_name}] Error cleaning log file for process {process_id}: {str(e)}")

            # Remove from tracking dictionaries
            processes.pop(process_id, None)
            process_termination_flags.pop(process_id, None)
            process_cleanup_locks.pop(process_id, None)
            
            logging.info(status_message)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)

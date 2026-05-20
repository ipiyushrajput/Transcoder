# Transcoder System — Architecture Reference

A production-grade media transcoding platform modeled after AWS MediaConvert (VOD) and AWS MediaLive (live), built on a Python/Flask backend and a React/MUI frontend. FFmpeg is the core processing engine for all encode and packaging operations.

---

## Table of Contents

1. [Repository Layout](#repository-layout)
2. [Setup](#setup)
3. [Backend Architecture](#backend-architecture)
4. [Frontend Architecture](#frontend-architecture)
5. [Database Schema](#database-schema)
6. [API Reference](#api-reference)
7. [FFmpeg Command Structure](#ffmpeg-command-structure)
8. [ESAM Ad Signaling](#esam-ad-signaling)
9. [S3 Upload Strategy](#s3-upload-strategy)
10. [Video Templates](#video-templates)
11. [Key Design Decisions](#key-design-decisions)
12. [Legacy Scripts](#legacy-scripts)

---

## Repository Layout

```
transcoder/
├── backend/
│   ├── app.py                    # Flask entry point, port 5001
│   ├── database.py               # MySQL connection (PyMySQL + SQLAlchemy)
│   ├── vod_transcoder.py         # VOD FFmpeg engine
│   ├── live_transcoder.py        # Live FFmpeg engine
│   ├── esam_processor.py         # ESAM XML parser & HLS marker injector
│   ├── input_validator.py        # ffprobe-based input validation
│   ├── s3_uploader.py            # S3 upload with watchdog file watcher
│   ├── requirements.txt
│   └── routes/
│       ├── vod_routes.py         # VOD API endpoints
│       ├── live_routes.py        # Live API endpoints
│       └── common_routes.py      # Shared: jobs, status, probe, templates
└── frontend/
    ├── package.json              # React + Vite + MUI
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── api/transcoder.js     # Axios client, base URL http://localhost:5001
        ├── components/
        │   ├── TranscoderPage.jsx     # Mode toggle: VOD | LIVE
        │   ├── VOD/
        │   │   ├── VODTranscoder.jsx
        │   │   ├── InputSection.jsx   # Input type, URL, validate, clips, subtitles
        │   │   ├── OutputSection.jsx  # HLS/MP4, S3/local, segment config
        │   │   ├── VideoAudioConfig.jsx  # Codec, bitrate, profile, template
        │   │   └── AdSignaling.jsx    # ESAM SCC + MCC XML inputs
        │   ├── Live/
        │   │   ├── LiveTranscoder.jsx
        │   │   ├── InputSection.jsx
        │   │   ├── OutputSection.jsx
        │   │   └── VideoAudioConfig.jsx
        │   └── shared/
        │       ├── JobsTable.jsx      # Active + history jobs table
        │       └── JobDetailModal.jsx
        └── theme/theme.js
```

---

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- MySQL 8.x running at `localhost:3306`
- FFmpeg with libx264 and libx265 support (ffprobe must also be on PATH or configured)
- AWS credentials configured if S3 or MediaPackage destinations are used

### Backend

```bash
cd transcoder/backend
pip install -r requirements.txt
python app.py          # starts on http://localhost:5001
```

**requirements.txt** key packages:

| Package | Version | Purpose |
|---|---|---|
| flask | 3.0.3 | HTTP server |
| flask-cors | 4.0.1 | Cross-origin requests from React dev server |
| pydantic | 2.7.4 | Request body validation |
| pymysql | 1.1.1 | MySQL driver |
| sqlalchemy | 2.0.31 | ORM / connection pool |
| flask-sqlalchemy | 3.1.1 | Flask-SQLAlchemy integration |
| boto3 / botocore | 1.34.x | AWS S3 and MediaPackage SDK |
| watchdog | 4.0.1 | Filesystem events for real-time S3 upload |
| lxml | 5.2.2 | Fast ESAM XML parsing |
| requests | 2.32.3 | HTTP input URL validation |
| python-dotenv | 1.0.1 | .env file support |

### Database

```sql
-- Connection
host: localhost
port: 3306
user: root
password: Piyush@23
database: transcoder_db
```

Run the schema migrations (see [Database Schema](#database-schema)) once before first start.

### Frontend

```bash
cd transcoder/frontend
npm install
npm run dev       # Vite dev server, proxies /api -> http://localhost:5001
npm run build     # Production build to dist/
```

---

## Backend Architecture

### app.py

Flask application factory. Registers blueprints from `routes/`, initialises SQLAlchemy, and sets `CORS` to allow all origins. Runs on port **5001**.

```python
app.run(host="0.0.0.0", port=5001, debug=False)
```

### database.py

Creates a SQLAlchemy engine against MySQL using PyMySQL as the dialect driver:

```
mysql+pymysql://root:Piyush@23@localhost:3306/transcoder_db
```

Exposes a `db` session factory used by all route modules. Connection pool settings follow SQLAlchemy defaults with `pool_recycle=3600` to survive MySQL's default 8-hour idle timeout.

### vod_transcoder.py

Orchestrates the full VOD pipeline in sequence:

1. **Input validation** — delegates to `input_validator.py`
2. **Clipping** — if `job_clips` rows exist, builds an `ffconcat` manifest for video and clips subtitle segments individually
3. **Subtitle processing** — generates a separate HLS subtitle playlist (`channel_{lang}-vtt.m3u8`) then updates the master playlist with `#EXT-X-MEDIA:TYPE=SUBTITLES`
4. **Audio normalisation (optional)** — two-pass loudnorm: analysis pass captures `input_i`, `input_lra`, `input_tp`; encode pass applies measured values
5. **Multi-bitrate HLS encode** — single FFmpeg process with `filter_complex` split + per-stream codec parameters (see [FFmpeg Command Structure](#ffmpeg-command-structure))
6. **MP4 output (optional)** — a separate FFmpeg pass writing a progressive MP4
7. **ESAM injection** — post-encode, calls `esam_processor.py` to insert CUE-OUT/CUE-OUT-CONT/CUE-IN tags into variant playlists
8. **Upload** — calls `s3_uploader.py` or copies to a local path

The FFmpeg subprocess PID is stored in the `jobs.process_pid` column so the process can be killed via `POST /api/vod/stop`.

### live_transcoder.py

Handles continuous live streams. Key differences from VOD:

- **Input types**: RTMP (`rtmp://`), SRT (`srt://`), HLS (`http(s)://`), or a local file looped with `-stream_loop -1`
- **Output types**: HLS to S3 (real-time watchdog upload), HLS to local path, RTMP re-stream, or AWS MediaPackage ingest
- **Playlist type**: `event` or `live` (sliding window controlled by `hls_list_size`)
- Uses `subprocess.Popen` (non-blocking) so the Flask response returns immediately with the `job_id`
- Process lifecycle is managed by a background monitor thread that updates `jobs.status` when FFmpeg exits

MediaPackage ingest uses HTTP PUT with Basic Auth (`mediapackage_user` / `mediapackage_password`), passing the HLS output URL directly to FFmpeg's `-hls_segment_filename` as an HTTP destination.

### esam_processor.py

Implements the full ESAM (Event Signaling and Management) workflow:

**Parsing** (`parse_esam_xml_string`):
- Parses SCC (Signal Conditioning Configuration) XML using the CableLabs namespace `urn:cablelabs:iptvservices:esam:xsd:signal:1`
- Extracts `NPTPoint.nptPoint` (float seconds), `segmentTypeId` (52 = CUE-OUT, 53 = CUE-IN), `segmentEventId`, and ISO 8601 duration (`PT{n}S`)
- Returns a sorted list of events by NPT timestamp

**Injection** (`inject_elemental_markers`):
- Walks each variant `.m3u8` file, accumulates segment boundaries and durations
- For each ESAM event, finds the containing segment by time range
- Inserts `#EXT-X-CUE-OUT:{duration}` before the segment, then `#EXT-X-CUE-OUT-CONT:{elapsed}/{duration}` before each subsequent segment until elapsed >= duration, then `#EXT-X-CUE-IN`
- Duplicate insertion is prevented by a proximity check (`has_marker_near`) scanning ±3 lines
- Segment type 53 inserts only `#EXT-X-CUE-IN` (no CUE-OUT-CONT chain)
- Results are written back to the `.m3u8` file in place

The MCC (Manifest Confirm Condition) XML is stored in the database for audit purposes but is not currently applied to playlists server-side; it is passed through to any downstream ad decision server.

### input_validator.py

Uses `ffprobe` to interrogate a URL or local file before starting a job:

```bash
ffprobe -v error -show_streams -show_format -of json <input>
```

Returns structured metadata: codec names, width, height, duration, bitrate, frame rate (as a `Fraction` to handle `30000/1001` style values), audio sample rate, and channel count. The result is surfaced to the UI via `POST /api/vod/probe` without starting a job.

For HTTP/HTTPS inputs, a `HEAD` request is issued first to detect 403/404 before spending time on the ffprobe call. SSL certificate verification is disabled to handle self-signed or expired certificates on content delivery origins.

### s3_uploader.py

Two complementary upload mechanisms running in parallel:

**Watchdog observer** (`S3UploadHandler extends FileSystemEventHandler`):
- `on_created`: immediately uploads `.ts` segments
- `on_modified`: waits 500 ms then uploads `.m3u8` playlists (FFmpeg rewrites them frequently)
- `on_moved`: handles FFmpeg's write-to-temp-then-rename pattern

**Periodic scanner** (background thread, 2-second interval):
- Safety net for any files missed by the inotify event queue under high load
- Tracks already-uploaded paths in a `set` to avoid redundant PUTs

On job stop or natural completion, `upload_all_remaining_files` does a final glob sweep before the temp directory is deleted.

All uploads go to `s3://{s3_bucket}/{s3_path}/` with the S3 key computed as `s3_path + relative_path_under_temp_dir`. The S3 client is `boto3.client('s3')` using the ambient AWS credential chain (instance profile, env vars, or `~/.aws/credentials`).

CloudFront playback URLs are constructed as:
```
https://{s3_cloudfront_domain}/{s3_path}/{master_filename}.m3u8
```

### routes/vod_routes.py

Blueprint prefix: `/api/vod`

| Method | Path | Action |
|---|---|---|
| POST | `/validate-input` | Lightweight URL reachability check |
| POST | `/probe` | Full ffprobe metadata extraction |
| POST | `/start` | Create job record, launch FFmpeg subprocess |
| POST | `/stop` | Send SIGTERM (then SIGKILL after 10 s) to process_pid |

### routes/live_routes.py

Blueprint prefix: `/api/live`

| Method | Path | Action |
|---|---|---|
| POST | `/validate-input` | URL reachability check for stream sources |
| POST | `/start` | Create job record, launch live FFmpeg subprocess |
| POST | `/stop` | Terminate live FFmpeg process |

### routes/common_routes.py

Blueprint prefix: `/api`

| Method | Path | Action |
|---|---|---|
| GET | `/jobs` | List all jobs (active + history), ordered by `created_at` desc |
| GET | `/jobs/:job_id` | Single job detail including variants and clips |
| GET | `/jobs/:job_id/logs` | Tail FFmpeg stderr log (last N lines) |
| DELETE | `/jobs/:job_id` | Remove job record (does not stop running process) |
| GET | `/templates` | Return video template definitions from config |
| GET | `/status` | System health: active process count, DB connectivity |

---

## Frontend Architecture

### Technology Stack

- **React 18** with functional components and hooks
- **Vite** for bundling and dev server (proxies `/api` to `http://localhost:5001`)
- **MUI v5** (Material-UI) for all UI components
- **Axios** as the HTTP client (`src/api/transcoder.js`, base URL `http://localhost:5001`)

### TranscoderPage.jsx

Top-level component. Renders a tab/toggle control to switch between VOD mode and LIVE mode. Shared state (job list, active job) is lifted here and passed down as props.

### VOD Components

**VODTranscoder.jsx** — container that composes the four VOD sub-sections and manages form state.

**InputSection.jsx**
- Input type selector: URL, local file path
- URL text field with a "Validate" button (calls `POST /api/vod/validate-input`)
- "Probe" button opens a metadata dialog (calls `POST /api/vod/probe`)
- Clip editor: list of `{start_timecode, end_timecode}` pairs in `HH:MM:SS:FF` SMPTE format
- Subtitle section: URL or file path input, language code selector (BCP-47, e.g. `en`, `es`)

**OutputSection.jsx**
- Output format toggle: HLS or MP4
- Destination selector: S3, local path
- S3 fields: bucket, path prefix, optional CloudFront domain
- Segment length (seconds), HLS playlist type (`vod` / `event` / `live`), HLS flags, `hls_list_size`
- Local path field when local destination is selected

**VideoAudioConfig.jsx**
- Template dropdown (populated from `GET /api/templates`)
- Per-variant row editor: resolution (WxH), video codec (libx264/libx265), bitrate, framerate, GOP, reference frames, H.264/H.265 profile, level, audio codec, audio bitrate, sample rate
- Add/remove variant rows

**AdSignaling.jsx**
- Toggle to enable ESAM
- SCC XML textarea (Signal Conditioning Configuration — the primary signal placement document)
- MCC XML textarea (Manifest Confirm Condition — audit/passthrough document)
- Both are stored verbatim in `jobs.esam_scc_xml` and `jobs.esam_mcc_xml`

### Live Components

**LiveTranscoder.jsx** — container for live mode.

**Live/InputSection.jsx**
- Input protocol selector: RTMP, SRT, HLS, File
- Source URL / path field
- Connection validation

**Live/OutputSection.jsx**
- Output type: HLS or RTMP re-stream
- Destination: S3, local, MediaPackage
- MediaPackage fields: ingest URL, username, password
- RTMP output URL field
- Segment and playlist configuration

**Live/VideoAudioConfig.jsx** — same per-variant editor as VOD, without the ESAM section.

### Shared Components

**JobsTable.jsx** — MUI `DataGrid` or custom table showing all jobs. Columns: job name, type (VOD/LIVE), status (badge), input URL, output destination, playback URL, started_at, actions (view detail, delete, stop).

**JobDetailModal.jsx** — drawer/modal showing full job record: all metadata fields, variant table, clip list, ESAM settings, and a scrollable log tail auto-refreshing every 5 seconds via `GET /api/jobs/:job_id/logs`.

### theme/theme.js

MUI theme configuration. Dark mode with a blue primary accent matching typical broadcast/OTT tool aesthetics.

---

## Database Schema

MySQL database `transcoder_db` at `localhost:3306` (user `root`, password `Piyush@23`).

### jobs

Primary job tracking table. One row per transcoding job (VOD or LIVE).

| Column | Type | Notes |
|---|---|---|
| id | INT AUTO_INCREMENT PK | |
| job_id | VARCHAR(36) | UUID, unique |
| type | ENUM('VOD','LIVE') | |
| status | ENUM('pending','running','completed','failed','stopped') | |
| name | VARCHAR(255) | User-supplied job label |
| input_url | TEXT | Source URL or local path |
| input_type | VARCHAR(50) | url, local, rtmp, srt, hls, file |
| output_type | VARCHAR(10) | hls, mp4, rtmp |
| output_destination | VARCHAR(20) | s3, local, mediapackage |
| s3_bucket | VARCHAR(255) | |
| s3_path | VARCHAR(1024) | Key prefix within bucket |
| s3_cloudfront_domain | VARCHAR(255) | Used to build playback URL |
| local_path | VARCHAR(1024) | Filesystem output path |
| mediapackage_url | TEXT | MediaPackage ingest endpoint |
| mediapackage_user | VARCHAR(255) | HTTP Basic Auth username |
| mediapackage_password | VARCHAR(255) | HTTP Basic Auth password |
| master_filename | VARCHAR(255) | e.g. `channel` → `channel.m3u8` |
| segment_length | INT | HLS segment duration in seconds (default 6) |
| hls_playlist_type | VARCHAR(10) | vod, event, or live |
| hls_flags | VARCHAR(255) | e.g. `independent_segments` |
| hls_list_size | INT | Sliding window size (live mode) |
| preset | VARCHAR(50) | FFmpeg encoder preset (e.g. `slower`) |
| subtitle_url | TEXT | WebVTT or SRT source |
| subtitle_language | VARCHAR(10) | BCP-47 language tag |
| esam_enabled | TINYINT(1) | |
| esam_scc_xml | LONGTEXT | Full SCC XML payload |
| esam_mcc_xml | LONGTEXT | Full MCC XML payload |
| rtmp_output_url | TEXT | RTMP push destination (live re-stream) |
| playback_url | TEXT | Final viewer-facing URL |
| process_pid | INT | OS PID of the FFmpeg subprocess |
| error_message | TEXT | FFmpeg stderr excerpt on failure |
| started_at | DATETIME | |
| completed_at | DATETIME | |
| created_at | DATETIME | DEFAULT NOW() |
| updated_at | DATETIME | ON UPDATE NOW() |

### job_variants

One row per output rendition (ladder rung). FK to `jobs.id`.

| Column | Type | Notes |
|---|---|---|
| id | INT AUTO_INCREMENT PK | |
| job_id | INT | FK → jobs.id |
| width | INT | e.g. 1920 |
| height | INT | e.g. 1080 |
| video_codec | VARCHAR(20) | libx264 or libx265 |
| video_bitrate | VARCHAR(20) | e.g. `3000k` |
| framerate | VARCHAR(10) | e.g. `30`, `29.97` |
| gop | INT | GOP size in frames or seconds (see GopSizeUnits) |
| reference_frames | INT | `-refs` parameter |
| profile | VARCHAR(20) | main, high, etc. |
| level | VARCHAR(10) | e.g. `4`, `3.1` |
| audio_codec | VARCHAR(20) | aac |
| audio_bitrate | VARCHAR(20) | e.g. `128k` |
| sample_rate | INT | e.g. 48000 |
| bandwidth | INT | Declared BANDWIDTH in master playlist (bps) |
| created_at | DATETIME | |

### job_clips

Input clipping segments, processed in order. FK to `jobs.id`.

| Column | Type | Notes |
|---|---|---|
| id | INT AUTO_INCREMENT PK | |
| job_id | INT | FK → jobs.id |
| start_timecode | VARCHAR(20) | SMPTE `HH:MM:SS:FF` |
| end_timecode | VARCHAR(20) | SMPTE `HH:MM:SS:FF` |
| clip_order | INT | Determines concat sequence |
| created_at | DATETIME | |

---

## API Reference

All endpoints are prefixed at `http://localhost:5001`. The frontend Axios client (`src/api/transcoder.js`) sets this as `baseURL`.

### VOD Endpoints

#### POST /api/vod/validate-input

Quick reachability check without probing codec metadata.

Request body:
```json
{ "url": "https://example.com/video.mp4" }
```

Response `200`:
```json
{ "valid": true, "message": "URL is accessible" }
```

Response `400`:
```json
{ "valid": false, "message": "Input URL returned 404 Not Found" }
```

#### POST /api/vod/probe

Full ffprobe interrogation. Returns stream metadata.

Request body:
```json
{ "url": "https://example.com/video.mp4" }
```

Response `200`:
```json
{
  "duration": 3600.0,
  "video": { "codec": "h264", "width": 1920, "height": 1080, "fps": 29.97 },
  "audio": { "codec": "aac", "sample_rate": 48000, "channels": 2 }
}
```

#### POST /api/vod/start

Creates a job record and starts the VOD FFmpeg pipeline.

Request body:
```json
{
  "name": "My VOD Job",
  "input_url": "https://example.com/video.mp4",
  "input_type": "url",
  "output_type": "hls",
  "output_destination": "s3",
  "s3_bucket": "my-bucket",
  "s3_path": "output/my-vod-job",
  "s3_cloudfront_domain": "https://d123.cloudfront.net",
  "master_filename": "channel",
  "segment_length": 6,
  "hls_playlist_type": "vod",
  "hls_flags": "independent_segments",
  "preset": "slower",
  "subtitle_url": "https://example.com/subs.vtt",
  "subtitle_language": "en",
  "esam_enabled": true,
  "esam_scc_xml": "<SignalProcessingNotification>...</SignalProcessingNotification>",
  "esam_mcc_xml": "<ManifestConfirmConditionNotification>...</ManifestConfirmConditionNotification>",
  "variants": [
    {
      "width": 1920, "height": 1080,
      "video_codec": "libx264", "video_bitrate": "3000k",
      "framerate": "30", "gop": 6,
      "reference_frames": 2, "profile": "high", "level": "4",
      "audio_codec": "aac", "audio_bitrate": "128k", "sample_rate": 48000
    }
  ],
  "clips": [
    { "start_timecode": "00:01:00:00", "end_timecode": "00:05:00:00", "clip_order": 1 }
  ]
}
```

Response `202`:
```json
{ "job_id": "550e8400-e29b-41d4-a716-446655440000" }
```

#### POST /api/vod/stop

Request body:
```json
{ "job_id": "550e8400-e29b-41d4-a716-446655440000" }
```

Sends SIGTERM to the stored PID; escalates to SIGKILL after 10 seconds if the process has not exited.

### Live Endpoints

#### POST /api/live/validate-input

Same contract as VOD validate-input, adapted for stream URLs (RTMP, SRT).

#### POST /api/live/start

Request body (representative):
```json
{
  "name": "My Live Channel",
  "input_url": "rtmp://ingest.example.com/live/stream-key",
  "input_type": "rtmp",
  "output_type": "hls",
  "output_destination": "s3",
  "s3_bucket": "my-live-bucket",
  "s3_path": "live/channel1",
  "s3_cloudfront_domain": "https://d456.cloudfront.net",
  "master_filename": "index",
  "segment_length": 6,
  "hls_playlist_type": "event",
  "hls_list_size": 5,
  "variants": [ ... ]
}
```

Response `202`:
```json
{ "job_id": "..." }
```

#### POST /api/live/stop

Same contract as `POST /api/vod/stop`.

### Common Endpoints

#### GET /api/jobs

Returns all jobs ordered by `created_at` descending. Optionally supports `?type=VOD`, `?status=running`.

#### GET /api/jobs/:job_id

Full job detail including nested `variants` array and `clips` array.

#### GET /api/jobs/:job_id/logs

Returns last 200 lines of FFmpeg stderr log for the job. Frontend polls this every 5 seconds in `JobDetailModal`.

#### DELETE /api/jobs/:job_id

Removes the job record from the database. Does not stop a running process (use the stop endpoint first).

#### GET /api/templates

Returns the video template definitions from the backend configuration. Used to populate the template dropdown in `VideoAudioConfig.jsx`.

#### GET /api/status

```json
{
  "status": "ok",
  "active_jobs": 3,
  "db": "connected"
}
```

---

## FFmpeg Command Structure

### VOD Multi-Bitrate HLS

The central VOD encode is a single FFmpeg invocation using `filter_complex` to split the decoded video into N renditions without re-reading the input:

```
ffmpeg -y
  -thread_queue_size 1024
  [-t <duration>]
  [-safe 0]                          # only when input is an ffconcat file
  -i <input>
  -filter_complex "
    [0:v]split=N[v0][v1]...[vN-1];
    [v0]scale=w=1920:h=1080[v0out];
    [v1]scale=w=1280:h=720[v1out];
    ...
    [0:a]asplit=N[a0out][a1out]...[aN-1out]
  "
  # Per-rendition output streams:
  -map [v0out] -map [a0out]
    -c:v:0 libx264 -x264-params "rc-lookahead=32:bframes=3:level=4:ref=2:nal-hrd=cbr:bitrate=3000:vbv-maxrate=3000:vbv-bufsize=6000"
    -preset:v:0 slower
    -b:v:0 3000k
    -force_key_frames:v:0 "expr:gte(t,n_forced*6)"
    -c:a:0 aac -b:a:0 128k
  -map [v1out] -map [a1out]
    -c:v:1 libx264 -x264-params "rc-lookahead=32:bframes=3:level=3.1:ref=2:nal-hrd=cbr:bitrate=1500:vbv-maxrate=1500:vbv-bufsize=3000"
    -preset:v:1 slower
    -b:v:1 1500k
    -force_key_frames:v:1 "expr:gte(t,n_forced*6)"
    -c:a:1 aac -b:a:1 128k
  ...
  -var_stream_map "v:0,a:0,name:1080p v:1,a:1,name:720p ..."
  -f hls
  -start_number 1
  -hls_time 6
  -hls_playlist_type vod
  -master_pl_name channel.m3u8
  -hls_segment_filename <output_dir>/channel_%v_%05d.ts
  -hls_flags independent_segments
  -hls_segment_type mpegts
  -y <output_dir>/channel_%v.m3u8
```

Key points:
- `split=N` / `asplit=N` avoids decoding the input N times.
- `force_key_frames "expr:gte(t,n_forced*6)"` aligns keyframes to segment boundaries regardless of source content, which is essential for correct HLS seeks.
- H.265 streams get `-tag:v:{i} hvc1` for Apple device compatibility.
- When H.265 is used, `crf` replaces the `-b:v` bitrate target (CRF values per rendition: 1080p→26.2, 720p→26.4, 540p→27.1, 360p→29.0).
- Deinterlacing: if a rendition has `interlace_mode = PROGRESSIVE` the filter prepends `yadif=mode=0:parity=auto:deint=1` before the scale filter.

### Input Clipping with ffconcat

When clips are defined, clipping is handled without re-encoding by writing an `ffconcat` manifest:

```
ffconcat version 1.0

file '/absolute/path/to/input.mp4'
inpoint 60.0
outpoint 300.0

file '/absolute/path/to/input.mp4'
inpoint 600.0
outpoint 900.0
```

This is passed as the input to the main encode command with `-safe 0`. Subtitle clips are extracted segment-by-segment with individual FFmpeg WebVTT copy commands, then concatenated into a second `ffconcat` file.

Timecode conversion from SMPTE `HH:MM:SS:FF` to fractional seconds uses Python's `fractions.Fraction` to handle non-integer frame rates (e.g. 29.97 = 30000/1001):

```python
seconds = hh * 3600 + mm * 60 + ss + ff / fps
```

### Subtitle HLS Playlist Generation

Subtitles are processed in a separate FFmpeg pass before the main encode:

```
ffmpeg -y [-safe 0] [-t <duration>]
  -i <subtitle_input_or_ffconcat>
  -map 0:0
  -c:s webvtt
  -f segment
  -segment_time 6
  -segment_list_type m3u8
  -hls_playlist_type vod
  -segment_list <output_dir>/channel_en-vtt.m3u8
  -segment_format webvtt
  <output_dir>/channel_en-vtt_%05d.vtt
```

After generation, the master playlist is rewritten to add:

```m3u8
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,LANGUAGE="en",URI="channel_en-vtt.m3u8"
```

And each `#EXT-X-STREAM-INF` line gets `,SUBTITLES="subs"` appended.

### Audio Normalisation (Two-Pass Loudnorm)

**Pass 1** (analysis only):
```
ffmpeg -y -i <input> -vn -af loudnorm=print_format=json -f null -
```
FFmpeg prints a JSON block to stderr containing `input_i`, `input_lra`, `input_tp`.

**Pass 2** (included in main encode filter_complex):
```
[0:a]loudnorm=I=-23:LRA=7:TP=-2:measured_I=<input_i>:measured_LRA=<input_lra>:measured_TP=<input_tp>:print_format=summary,asplit=N[a0out][a1out]...
```

Target levels follow EBU R128: integrated loudness −23 LUFS, LRA 7 LU, true peak −2 dBTP.

### Live Streaming

For live sources FFmpeg is launched with `subprocess.Popen` (non-blocking):

```
ffmpeg -hide_banner -loglevel error
  -stream_loop -1          # file loop (file input type only)
  -i <rtmp|srt|hls|file>
  -filter_complex "..."    # same split/scale structure as VOD
  ...per-rendition codec flags...
  -hls_time 6
  -hls_list_size 5         # sliding window
  -hls_flags delete_segments+independent_segments
  -hls_segment_filename <dest>/%v/segment%04d.ts
  -master_pl_name index.m3u8
  -var_stream_map "..."
  -f hls <dest>/%v.m3u8
```

For RTMP output, FFmpeg outputs to `flv` format targeting the configured RTMP URL. For MediaPackage, the HLS output destination is the MediaPackage ingest URL with credentials embedded.

---

## ESAM Ad Signaling

ESAM (CableLabs ESAM specification) is used to inject ad break markers into HLS playlists compatible with SCTE-35/SCTE-67 downstream ad decisioning systems.

### XML Namespaces

| Prefix | URI |
|---|---|
| esam | `urn:cablelabs:iptvservices:esam:xsd:signal:1` |
| sig | `urn:cablelabs:md:xsd:signaling:3.0` |
| common | `urn:cablelabs:iptvservices:esam:xsd:common:1` |

### Signal Types

| segmentTypeId | Meaning | HLS Tag Inserted |
|---|---|---|
| 52 | Ad break start (CUE-OUT) | `#EXT-X-CUE-OUT:{duration}` |
| 53 | Ad break end (CUE-IN) | `#EXT-X-CUE-IN` |

Between CUE-OUT and CUE-IN, each intermediate segment gets:
```
#EXT-X-CUE-OUT-CONT:{elapsed:.3f}/{duration_int}
```

### Injection Flow

1. Parse SCC XML → sorted list of `{npt, duration, segmentTypeId, segmentEventId}` events
2. After HLS encode completes, call `process_playlist(master_m3u8, events)`
3. If master: discover variant URIs from `#EXT-X-STREAM-INF` lines, inject into each variant
4. Each variant is modified in-place; the master playlist itself is not modified (markers live in variants only)
5. If subtitles are present, the subtitle playlist also gets markers injected

The implementation mirrors what AWS Elemental MediaConvert produces for ESAM-enabled jobs.

---

## S3 Upload Strategy

### Real-Time Upload (Watchdog + Periodic Scanner)

Two mechanisms run in parallel to ensure no segments are lost:

**Watchdog observer** reacts to filesystem events:
- `.ts` segments: uploaded immediately on `on_created`
- `.m3u8` playlists: uploaded on `on_modified` with a 500 ms stabilisation delay (FFmpeg rewrites the playlist after each segment)
- File renames: handled via `on_moved` (FFmpeg may write to a `.tmp` file then rename)

**Periodic scanner** (2-second cycle):
- Glob scan for `**/*.ts` and `**/*.m3u8`
- Skips already-uploaded paths tracked in a `set`
- Catches any events missed by the watchdog under high inotify load

### Cleanup

On stop or natural completion:
1. Watchdog observer is stopped (`observer.stop()` + `observer.join(timeout=5)`)
2. Periodic scanner stop event is set
3. `upload_all_remaining_files` performs a final glob sweep
4. `shutil.rmtree(temp_dir)` removes the local working directory
5. FFmpeg stderr log file is deleted

### S3 Key Structure

```
s3://{s3_bucket}/{s3_path}/{relative_path_under_temp_dir}
```

Example: if `s3_path = "output/my-vod"` and FFmpeg writes `channel_1080p.m3u8` to `{temp_dir}/output/my-vod/`, the S3 key becomes `output/my-vod/channel_1080p.m3u8`.

---

## Video Templates

Templates are named groups of rendition definitions stored in the backend configuration. The frontend populates the template dropdown from `GET /api/templates`.

### h264_standard

Four renditions using libx264 with CBR via `nal-hrd=cbr`:

| Name | Resolution | Bitrate | x264-params |
|---|---|---|---|
| 1080p | 1920x1080 | 3000 kbps | `rc-lookahead=32:bframes=3:level=4:ref=2:nal-hrd=cbr:bitrate=3000:vbv-maxrate=3000:vbv-bufsize=6000` |
| 720p | 1280x720 | 1500 kbps | `rc-lookahead=32:bframes=3:level=3.1:ref=2:nal-hrd=cbr:bitrate=1500:vbv-maxrate=1500:vbv-bufsize=3000` |
| 540p | 960x540 | 1000 kbps | `rc-lookahead=32:bframes=3:level=3.1:ref=2:nal-hrd=cbr:bitrate=1000:vbv-maxrate=1000:vbv-bufsize=2000` |
| 360p | 640x360 | 500 kbps | `rc-lookahead=32:bframes=3:level=3.1:ref=2:nal-hrd=cbr:bitrate=500:vbv-maxrate=500:vbv-bufsize=1000` |

All renditions: preset=`slower`, threads=4, GOP=6 seconds, PROGRESSIVE deinterlace, audio AAC 128k.

### h265_standard

Four renditions using libx265 with CRF-based quality targeting (not CBR):

| Name | Resolution | CRF | x265-params |
|---|---|---|---|
| 1080p | 1920x1080 | 26.2 | `rc-lookahead=32:bframes=3:level=4:ref=2:vbv-maxrate=3200:vbv-bufsize=6400` |
| 720p | 1280x720 | 26.4 | `rc-lookahead=32:bframes=3:level=3.1:ref=2:vbv-maxrate=1700:vbv-bufsize=3400` |
| 540p | 960x540 | 27.1 | `rc-lookahead=32:bframes=3:level=3.1:ref=2:vbv-maxrate=1000:vbv-bufsize=2000` |
| 360p | 640x360 | 29.0 | `rc-lookahead=32:bframes=3:level=3.1:ref=2:vbv-maxrate=500:vbv-bufsize=1000` |

H.265 outputs include `-tag:v hvc1` for compatibility with Apple HLS players. VBV bufsize is 2x maxrate in all cases.

---

## Key Design Decisions

**Single FFmpeg process for multi-bitrate encode**: Using `filter_complex` with `split`/`asplit` decodes the input once and encodes all renditions in a single pass. This minimises disk I/O and is more efficient than running a separate FFmpeg per rendition, at the cost of higher peak CPU usage.

**Process PID tracking over subprocess handles**: The Flask backend stores the OS PID in the database rather than holding a subprocess handle in memory. This means the stop endpoint works correctly even after a backend restart, as long as the FFmpeg process is still running.

**ffconcat for clipping instead of trim filter**: Using an `ffconcat` manifest with `inpoint`/`outpoint` is faster than the `trim` filter because FFmpeg can seek directly to the inpoint without decoding from the beginning. The trade-off is that the first keyframe before the inpoint may be included (non-key-frame seeks may cause a brief visual artifact).

**Two-phase S3 upload (watchdog + scanner)**: The watchdog provides low-latency uploads for live streams; the scanner is a safety net for any events dropped during high inotify activity. Both share a `set` of uploaded paths to prevent duplicate PUTs.

**ESAM injection as post-process**: Markers are injected into `.m3u8` files after FFmpeg completes, not during encoding. This avoids any interaction with FFmpeg's HLS muxer and keeps the injection logic fully independent. The downside is that the final playlists are not available until the full encode finishes (acceptable for VOD; for live, markers would need to be inserted via a playlist rewrite daemon).

**Subtitle playlist as a separate FFmpeg pass**: FFmpeg's HLS muxer does not support mixing subtitle streams into the same multi-variant output when using `var_stream_map`. Running subtitles as a separate pass with the `segment` muxer (not the `hls` muxer) gives full control over segment timing and ensures the subtitle playlist type is set to `vod`.

**Pydantic v2 for request validation**: Request bodies are validated by Pydantic models before any processing begins. Validation errors return HTTP 400 with a structured error list. This prevents malformed requests from reaching FFmpeg command construction.

**Flask-CORS allowing all origins**: The development setup allows all origins. For production, restrict to the actual frontend domain.

**MySQL `pool_recycle=3600`**: MySQL closes idle connections after `wait_timeout` (default 8 hours), but under low traffic the pool can idle long enough to hit this. The 1-hour recycle ensures connections are periodically refreshed.

---

## Legacy Scripts

These files exist at the repository root and represent earlier standalone implementations. They are not used by the Flask application but contain useful reference logic.

### ffmpeg.py

A command-line VOD transcoder. Accepts arguments for `--input`, `--output`, `--template`, `--subtitle`, `--esam`, `--upload`, `--import` (MediaPackage), `--audio_norm`, `--generate-thumbnails`, `--duration`. Reads all configuration from `config.json`.

Key functions referenced and ported into the Flask backend:
- `timecode_to_seconds(tc, fps)` — SMPTE to float conversion
- `process_clippings(...)` — ffconcat generation for video and subtitles
- `process_subtitles(...)` — subtitle HLS playlist generation
- `update_master_playlist_for_subtitles(...)` — master M3U8 rewrite
- `run_loudnorm_analysis(...)` — two-pass loudnorm analysis
- `parse_esam_xml_string(...)` — ESAM XML parsing
- `inject_elemental_markers(...)` — per-variant CUE-OUT/CUE-IN injection
- `manage_mediapackage_vod_asset(...)` — full MediaPackage VOD lifecycle management
- `get_video_fps(...)` — ffprobe FPS extraction with Fraction parsing

### s3_transcoder.py

An earlier Flask application (port 5000) that handled live transcoding with real-time S3 upload. Uses the Watchdog + periodic scanner pattern that was carried forward into the full backend. Input validation (`validate_input_url`) and the `S3UploadHandler` class were ported directly. The `build_ffmpeg_command` function in this file constructs a simpler command (without `filter_complex`, using sequential `[0:v]scale` filters per rendition) and is superseded by the `filter_complex`-based approach in `vod_transcoder.py`.

### addevent.js

A React component (`AddEvent`) representing a UI prototype for the variant editor and job submission form. The production `VideoAudioConfig.jsx` and `VODTranscoder.jsx` components descend from this prototype. It shows the AVC 4K template definitions used in the legacy UI.

### config.json

Configuration file consumed by `ffmpeg.py`. Contains:
- `video_templates`: h264_standard and h265_standard rendition ladders (ported to backend config)
- `Esam.SignalProcessingNotification.SccXml`: sample ESAM SCC XML with 10 mid-roll + pre/post-roll events at NPT timestamps across a ~90-minute asset
- `Esam.ManifestConfirmConditionNotification.MccXml`: corresponding MCC XML
- `thumbnail_generation`: optional thumbnail extraction settings (interval, size, quality)
- `audio_normalization`: EBU R128 target levels
- `paths`: FFmpeg/ffprobe executable paths
- `s3.base_path`: default S3 destination prefix

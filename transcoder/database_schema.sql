-- Transcoder Database Schema
-- Run: mysql -h localhost -u root -p < database_schema.sql

CREATE DATABASE IF NOT EXISTS `transcoder_db`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `transcoder_db`;

CREATE TABLE IF NOT EXISTS `jobs` (
  `id`                    INT AUTO_INCREMENT PRIMARY KEY,
  `job_id`                VARCHAR(36) UNIQUE NOT NULL COMMENT 'UUID',
  `type`                  ENUM('VOD','LIVE') NOT NULL,
  `status`                ENUM('PENDING','RUNNING','COMPLETED','FAILED','STOPPED') NOT NULL DEFAULT 'PENDING',
  `name`                  VARCHAR(255),
  `input_url`             TEXT,
  `input_type`            VARCHAR(50),
  `output_type`           VARCHAR(50) COMMENT 'HLS or MP4 (VOD) / HLS or RTMP (Live)',
  `output_destination`    VARCHAR(50) COMMENT 'S3, LOCAL, MEDIAPACKAGE',
  `s3_bucket`             VARCHAR(255),
  `s3_path`               VARCHAR(500),
  `s3_cloudfront_domain`  VARCHAR(500),
  `local_path`            VARCHAR(500),
  `mediapackage_url`      VARCHAR(500),
  `mediapackage_user`     VARCHAR(255),
  `mediapackage_password` VARCHAR(255),
  `rtmp_output_url`       VARCHAR(500),
  `master_filename`       VARCHAR(255),
  `segment_length`        INT COMMENT 'HLS segment duration in seconds',
  `hls_playlist_type`     VARCHAR(50) COMMENT 'vod, event, live',
  `hls_flags`             VARCHAR(100),
  `hls_list_size`         INT,
  `preset`                VARCHAR(50) COMMENT 'FFmpeg encoder preset',
  `subtitle_url`          TEXT,
  `subtitle_language`     VARCHAR(10) DEFAULT 'en',
  `esam_enabled`          TINYINT(1) DEFAULT 0,
  `esam_scc_xml`          LONGTEXT,
  `esam_mcc_xml`          LONGTEXT,
  `playback_url`          TEXT,
  `process_pid`           INT,
  `error_message`         TEXT,
  `started_at`            DATETIME,
  `completed_at`          DATETIME,
  `created_at`            DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at`            DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_job_id (`job_id`),
  INDEX idx_type_status (`type`, `status`),
  INDEX idx_created (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `job_variants` (
  `id`               INT AUTO_INCREMENT PRIMARY KEY,
  `job_id`           VARCHAR(36) NOT NULL,
  `width`            INT,
  `height`           INT,
  `video_codec`      VARCHAR(50),
  `video_bitrate`    INT COMMENT 'bits per second',
  `framerate`        VARCHAR(20),
  `gop`              INT,
  `reference_frames` INT,
  `profile`          VARCHAR(50),
  `level`            VARCHAR(20),
  `audio_codec`      VARCHAR(50),
  `audio_bitrate`    INT COMMENT 'bits per second',
  `sample_rate`      INT COMMENT 'Hz',
  `bandwidth`        INT COMMENT 'estimated bandwidth for HLS manifest',
  `created_at`       DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`job_id`) REFERENCES `jobs`(`job_id`) ON DELETE CASCADE,
  INDEX idx_job_id (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `job_clips` (
  `id`              INT AUTO_INCREMENT PRIMARY KEY,
  `job_id`          VARCHAR(36) NOT NULL,
  `start_timecode`  VARCHAR(20) COMMENT 'HH:MM:SS:FF format',
  `end_timecode`    VARCHAR(20) COMMENT 'HH:MM:SS:FF format',
  `clip_order`      INT DEFAULT 0,
  `created_at`      DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`job_id`) REFERENCES `jobs`(`job_id`) ON DELETE CASCADE,
  INDEX idx_job_id (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

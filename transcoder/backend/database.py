import os
import logging
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.mysql import LONGTEXT
from datetime import datetime

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "Piyush@23")
DB_NAME = os.getenv("DB_NAME", "transcoder_db")

# URL-encode password to handle special characters like @
_encoded_pass = quote_plus(DB_PASS)
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{_encoded_pass}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), unique=True, nullable=False, index=True)
    type = Column(Enum("VOD", "LIVE"), nullable=False)
    status = Column(
        Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", "STOPPED"),
        default="PENDING",
        nullable=False,
    )
    name = Column(String(255))
    input_url = Column(Text)
    input_type = Column(String(50))
    output_type = Column(String(50))
    output_destination = Column(String(50))
    s3_bucket = Column(String(255))
    s3_path = Column(String(500))
    s3_cloudfront_domain = Column(String(500))
    local_path = Column(String(500))
    mediapackage_url = Column(String(500))
    mediapackage_user = Column(String(255))
    mediapackage_password = Column(String(255))
    rtmp_output_url = Column(String(500))
    master_filename = Column(String(255))
    segment_length = Column(Integer)
    hls_playlist_type = Column(String(50))
    hls_flags = Column(String(100))
    hls_list_size = Column(Integer)
    preset = Column(String(50))
    subtitle_url = Column(Text)
    subtitle_language = Column(String(10), default="en")
    esam_enabled = Column(Boolean, default=False)
    esam_scc_xml = Column(LONGTEXT)
    esam_mcc_xml = Column(LONGTEXT)
    playback_url = Column(Text)
    process_pid = Column(Integer)
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobVariant(Base):
    __tablename__ = "job_variants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
    width = Column(Integer)
    height = Column(Integer)
    video_codec = Column(String(50))
    video_bitrate = Column(Integer)
    framerate = Column(String(20))
    gop = Column(Integer)
    reference_frames = Column(Integer)
    profile = Column(String(50))
    level = Column(String(20))
    audio_codec = Column(String(50))
    audio_bitrate = Column(Integer)
    sample_rate = Column(Integer)
    bandwidth = Column(Integer)
    av1_preset = Column(Integer)  # AV1 speed knob (svtav1 0-13 / aom 0-8 / rav1e 0-10)
    created_at = Column(DateTime, default=datetime.utcnow)


class JobClip(Base):
    __tablename__ = "job_clips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
    start_timecode = Column(String(20))
    end_timecode = Column(String(20))
    clip_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


engine = None
SessionLocal = None


def init_db():
    global engine, SessionLocal
    try:
        # Ensure database exists
        root_engine = create_engine(
            f"mysql+pymysql://{DB_USER}:{_encoded_pass}@{DB_HOST}:{DB_PORT}/",
            echo=False,
        )
        with root_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            conn.commit()
        root_engine.dispose()

        engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=3600)
        Base.metadata.create_all(engine)
        _run_light_migrations(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logging.info(f"Database initialized: {DB_NAME}")
        return True
    except Exception as e:
        logging.error(f"Database initialization failed: {e}")
        return False


def _run_light_migrations(engine):
    """Add columns introduced after a table was first created. create_all()
    never ALTERs existing tables, so new columns (e.g. av1_preset) need this."""
    migrations = [
        ("job_variants", "av1_preset", "ALTER TABLE job_variants ADD COLUMN av1_preset INT"),
    ]
    with engine.connect() as conn:
        for table, column, ddl in migrations:
            try:
                exists = conn.execute(text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = :db AND table_name = :t AND column_name = :c"
                ), {"db": DB_NAME, "t": table, "c": column}).scalar()
                if not exists:
                    conn.execute(text(ddl))
                    conn.commit()
                    logging.info(f"Migration: added {table}.{column}")
            except Exception as e:
                logging.warning(f"Migration for {table}.{column} skipped: {e}")


def get_db():
    if SessionLocal is None:
        return None
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        return None


def close_db(db):
    if db:
        db.close()

"""AV1 encoder helpers shared by the VOD and Live transcoders.

AV1 (AOMedia Video 1) is a royalty-free codec that succeeds AVC/HEVC. FFmpeg
ships three software AV1 encoders, each with a different speed/quality/RAM
trade-off:

  * libsvtav1  (SVT-AV1)  — fastest; the production default for VOD & live.
                            Speed knob: -preset 0..13 (0=slowest/best quality,
                            13=fastest). Only supports 8-/10-bit 4:2:0.
  * libaom-av1 (libaom)   — reference encoder, highest quality, slowest.
                            Speed knob: -cpu-used 0..8. Needs -row-mt 1 and
                            tiling for acceptable speed. Widest pixel-format
                            support (4:2:2 / 4:4:4 / 10-/12-bit).
  * librav1e   (rav1e)    — Rust encoder, lowest RAM (~1/4 of SVT-AV1); good
                            for memory-constrained hosts. Speed knob:
                            -speed 0..10.

Mandatory / important notes when encoding AV1:
  * AV1 in HLS MUST use fragmented-MP4 (CMAF) segments, NOT MPEG-TS — players
    (Safari, hls.js) and Apple's HLS authoring spec do not support AV1-in-TS.
    Both transcoders switch the HLS segment type to fMP4 when any variant is
    AV1.
  * AV1 does not use the AVC/HEVC `-profile:v` / `-level:v` options; the level
    is derived by the encoder. We therefore skip those for AV1 variants.
  * SVT-AV1 only accepts yuv420p / yuv420p10le — we always output yuv420p.
  * Keyframe interval is set explicitly so HLS segments stay GOP-aligned.
"""

AV1_ENCODERS = {"libsvtav1", "libaom-av1", "librav1e"}

# Per-encoder speed-knob ranges (min, max, default).
_PRESET_RANGE = {
    "libsvtav1": (0, 13, 8),
    "libaom-av1": (0, 8, 5),
    "librav1e": (0, 10, 6),
}


def is_av1(codec: str) -> bool:
    return codec in AV1_ENCODERS


def variants_use_av1(variants: list) -> bool:
    return any(is_av1(v.get("video_codec", "")) for v in variants or [])


def clamp_av1_preset(codec: str, preset) -> int:
    lo, hi, default = _PRESET_RANGE.get(codec, (0, 13, 8))
    try:
        p = int(preset)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, p))


def av1_video_args(codec: str, index, bitrate: int, gop_frames: int,
                   preset, low_latency: bool = False) -> list:
    """Build the FFmpeg video-encoder args for one AV1 output.

    `index` selects the stream-specifier style so the same helper serves both
    callers:
      * VOD clip encoder — one video output per option, so codec/bitrate use
        `-c:v` / `-b:v` and the rest are unspecified (`-preset`, `-g`, …).
        Pass index=None.
      * Live HLS muxer — one command with many mapped outputs, so every option
        needs the `:v:{i}` stream specifier (`-c:v:0`, `-preset:v:0`, …).
        Pass index=i.

    Rate control is bitrate-targeted (streaming ladders need predictable
    bitrates). `low_latency=True` tunes for live.
    """
    p = clamp_av1_preset(codec, preset)
    br = int(bitrate)
    if index is None:
        cspec, ospec = ":v", ""       # -c:v / -b:v ; -preset / -g (bare)
    else:
        cspec = ospec = f":v:{index}"  # -c:v:0 / -preset:v:0

    args = [f"-c{cspec}", codec, f"-b{cspec}", str(br)]

    if codec == "libsvtav1":
        # scd=0 disables scene-change detection so keyframes land only on the
        # forced GOP grid (uniform HLS segments). keyint in frames.
        svt = f"keyint={gop_frames}:scd=0"
        if low_latency:
            svt += ":pred-struct=1:lookahead=0"
        args += [
            f"-preset{ospec}", str(p),
            f"-g{ospec}", str(gop_frames),
            f"-svtav1-params{ospec}", svt,
        ]
    elif codec == "libaom-av1":
        # row-mt + tiles are effectively mandatory for usable speed.
        # keyint_min == g forces a fixed GOP (no adaptive keyframes).
        args += [
            f"-cpu-used{ospec}", str(p),
            f"-row-mt{ospec}", "1",
            f"-tiles{ospec}", "2x2",
            f"-g{ospec}", str(gop_frames),
            f"-keyint_min{ospec}", str(gop_frames),
            f"-maxrate{ospec}", str(br),
            f"-bufsize{ospec}", str(br * 2),
        ]
        if low_latency:
            args += [f"-usage{ospec}", "realtime"]
    elif codec == "librav1e":
        rav1e = f"speed={p}:tiles=4"
        if low_latency:
            rav1e += ":low_latency=true"
        args += [
            f"-speed{ospec}", str(p),
            f"-g{ospec}", str(gop_frames),
            f"-rav1e-params{ospec}", rav1e,
        ]
    return args


def av1_codecs_string(height: int, audio: str = "mp4a.40.2") -> str:
    """RFC 6381 codecs attribute for an 8-bit Main-profile AV1 variant.

    Format: av01.<profile>.<seq_level_idx><tier>.<bitdepth>
      profile 0 = Main, tier M = Main, bitdepth 08 = 8-bit.
    seq_level_idx by resolution (approximate, players are lenient):
      <=720p -> 3.1 (05), <=1080p -> 4.0 (08), <=1440p -> 5.0 (12), else 5.1 (13).
    """
    h = int(height or 0)
    if h <= 720:
        lvl = "05"
    elif h <= 1080:
        lvl = "08"
    elif h <= 1440:
        lvl = "12"
    else:
        lvl = "13"
    return f"av01.0.{lvl}M.08,{audio}"

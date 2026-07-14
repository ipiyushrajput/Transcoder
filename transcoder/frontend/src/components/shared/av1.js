// AV1 encoder metadata shared by the VOD and Live video/audio config forms.
//
// AV1 is a royalty-free codec succeeding AVC/HEVC. FFmpeg has three software
// AV1 encoders; the user picks the library that fits their need.

export const AV1_LIBRARIES = [
  {
    value: 'libsvtav1',
    label: 'SVT-AV1 (libsvtav1)',
    hint: 'Fastest — best speed/quality balance. Recommended default for VOD and live streaming. Speed preset 0 (slowest/best) → 13 (fastest).',
    max: 13,
    default: 8,
  },
  {
    value: 'libaom-av1',
    label: 'libaom-av1 (reference)',
    hint: 'Highest quality but slowest. Choose when encode time is not a constraint (archival / premium VOD). cpu-used 0 (slowest/best) → 8 (fastest).',
    max: 8,
    default: 5,
  },
  {
    value: 'librav1e',
    label: 'rav1e (librav1e)',
    hint: 'Lowest memory footprint (~1/4 of SVT-AV1). Good for memory-constrained hosts. Speed 0 (slowest/best) → 10 (fastest).',
    max: 10,
    default: 6,
  },
]

export const AV1_ENCODERS = AV1_LIBRARIES.map((l) => l.value)

export const isAv1 = (codec) => AV1_ENCODERS.includes(codec)

export const av1Meta = (codec) => AV1_LIBRARIES.find((l) => l.value === codec) || AV1_LIBRARIES[0]

// Clamp a preset value into the valid range for the chosen library.
export const clampAv1Preset = (codec, preset) => {
  const meta = av1Meta(codec)
  const p = Number.isFinite(+preset) ? +preset : meta.default
  return Math.max(0, Math.min(meta.max, p))
}

import React from 'react'
import {
  Box, Card, CardContent, Typography, Grid, FormControl, InputLabel,
  Select, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Divider,
} from '@mui/material'
import StorageIcon from '@mui/icons-material/Storage'
import CloudIcon from '@mui/icons-material/Cloud'
import FolderIcon from '@mui/icons-material/Folder'
import MovieIcon from '@mui/icons-material/Movie'
import StreamIcon from '@mui/icons-material/Stream'

const OUTPUT_TYPES = [
  { value: 'HLS', label: 'HLS', icon: <StreamIcon fontSize="small" /> },
  { value: 'MP4', label: 'MP4 File', icon: <MovieIcon fontSize="small" /> },
]

const DESTINATIONS = [
  { value: 'S3', label: 'Amazon S3', icon: <CloudIcon fontSize="small" /> },
  { value: 'LOCAL', label: 'Local Directory', icon: <FolderIcon fontSize="small" /> },
]

const HLS_PLAYLIST_TYPES = [
  { value: 'vod', label: 'VOD (Complete playlist)' },
  { value: 'event', label: 'EVENT (Growing playlist)' },
  { value: 'live', label: 'LIVE (Rolling window)' },
]

const HLS_FLAGS = [
  { value: 'independent_segments', label: 'independent_segments' },
  { value: 'delete_segments', label: 'delete_segments' },
  { value: 'append_list', label: 'append_list' },
  { value: 'single_file', label: 'single_file' },
  { value: 'program_date_time', label: 'program_date_time' },
]

const PRESETS = [
  { value: 'ultrafast', label: 'Ultra Fast' },
  { value: 'superfast', label: 'Super Fast' },
  { value: 'veryfast', label: 'Very Fast' },
  { value: 'faster', label: 'Faster' },
  { value: 'fast', label: 'Fast' },
  { value: 'medium', label: 'Medium (Recommended)' },
  { value: 'slow', label: 'Slow' },
  { value: 'slower', label: 'Slower' },
  { value: 'veryslow', label: 'Very Slow (Best Quality)' },
]

export default function OutputSection({ value, onChange }) {
  const set = (field, val) => onChange(prev => ({ ...prev, [field]: val }))

  const isHLS = (value.output_type || 'HLS') === 'HLS'
  const isS3 = (value.output_destination || 'LOCAL') === 'S3'

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box component="span" sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: 'primary.main', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>2</Box>
          Output Configuration
        </Typography>

        {/* Output Type */}
        <Box sx={{ mb: 2.5 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Output Format</Typography>
          <ToggleButtonGroup
            value={value.output_type || 'HLS'}
            exclusive
            onChange={(_, v) => v && set('output_type', v)}
            size="small"
          >
            {OUTPUT_TYPES.map((t) => (
              <ToggleButton key={t.value} value={t.value} sx={{ gap: 0.5, px: 2 }}>
                {t.icon} {t.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        {/* Destination */}
        <Box sx={{ mb: 2.5 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Destination</Typography>
          <ToggleButtonGroup
            value={value.output_destination || 'LOCAL'}
            exclusive
            onChange={(_, v) => v && set('output_destination', v)}
            size="small"
          >
            {DESTINATIONS.map((d) => (
              <ToggleButton key={d.value} value={d.value} sx={{ gap: 0.5, px: 2 }}>
                {d.icon} {d.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        {/* S3 Config */}
        {isS3 && (
          <Box sx={{ mb: 2.5, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
            <Typography variant="subtitle2" sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <CloudIcon fontSize="small" color="primary" /> Amazon S3 Configuration
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={4}>
                <TextField fullWidth size="small" label="S3 Bucket Name *" value={value.s3_bucket || ''} onChange={(e) => set('s3_bucket', e.target.value)} placeholder="my-video-bucket" />
              </Grid>
              <Grid item xs={12} md={4}>
                <TextField fullWidth size="small" label="S3 Key Prefix / Path" value={value.s3_path || ''} onChange={(e) => set('s3_path', e.target.value)} placeholder="outputs/my-video" />
              </Grid>
              <Grid item xs={12} md={4}>
                <TextField fullWidth size="small" label="CloudFront Domain (optional)" value={value.s3_cloudfront_domain || ''} onChange={(e) => set('s3_cloudfront_domain', e.target.value)} placeholder="https://d1234abc.cloudfront.net" />
              </Grid>
            </Grid>
          </Box>
        )}

        {/* Local Config */}
        {!isS3 && (
          <Box sx={{ mb: 2.5 }}>
            <TextField fullWidth size="small" label="Local Output Directory *" value={value.local_path || ''} onChange={(e) => set('local_path', e.target.value)} placeholder="/var/www/html/videos/output" />
          </Box>
        )}

        <Divider sx={{ my: 2 }} />

        {/* HLS Settings */}
        {isHLS && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1.5 }}>HLS Settings</Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={3}>
                <TextField
                  fullWidth size="small" label="Master Filename *" value={value.master_filename || 'master'}
                  onChange={(e) => set('master_filename', e.target.value)} placeholder="master"
                  helperText="Without .m3u8 extension"
                />
              </Grid>
              <Grid item xs={12} md={2}>
                <TextField
                  fullWidth size="small" type="number" label="Segment Length (s) *"
                  value={value.segment_length ?? 6} onChange={(e) => set('segment_length', parseInt(e.target.value, 10) || 6)}
                  inputProps={{ min: 1, max: 60 }}
                />
              </Grid>
              <Grid item xs={12} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>Playlist Type</InputLabel>
                  <Select value={value.hls_playlist_type || 'vod'} label="Playlist Type" onChange={(e) => set('hls_playlist_type', e.target.value)}>
                    {HLS_PLAYLIST_TYPES.map((t) => <MenuItem key={t.value} value={t.value}>{t.label}</MenuItem>)}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={2}>
                <TextField
                  fullWidth size="small" type="number" label="List Size (0=all)"
                  value={value.hls_list_size ?? 0}
                  onChange={(e) => set('hls_list_size', parseInt(e.target.value))}
                  inputProps={{ min: 0 }}
                />
              </Grid>
              <Grid item xs={12} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>HLS Flags</InputLabel>
                  <Select value={value.hls_flags || 'independent_segments'} label="HLS Flags" onChange={(e) => set('hls_flags', e.target.value)}>
                    {HLS_FLAGS.map((f) => <MenuItem key={f.value} value={f.value}>{f.label}</MenuItem>)}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </Box>
        )}

        {/* MP4 Settings */}
        {!isHLS && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1.5 }}>MP4 Settings</Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={4}>
                <TextField fullWidth size="small" label="Output Filename *" value={value.master_filename || 'output'} onChange={(e) => set('master_filename', e.target.value)} helperText="Without .mp4 extension" />
              </Grid>
            </Grid>
          </Box>
        )}

        <Divider sx={{ my: 2 }} />

        {/* Encoder Preset */}
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1.5 }}>Encoder Preset</Typography>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Preset</InputLabel>
            <Select value={value.preset || 'medium'} label="Preset" onChange={(e) => set('preset', e.target.value)}>
              {PRESETS.map((p) => <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>)}
            </Select>
          </FormControl>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            Slower preset = better quality, more CPU. Medium is recommended for production VOD.
          </Typography>
        </Box>
      </CardContent>
    </Card>
  )
}

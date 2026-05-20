import React from 'react'
import {
  Box, Card, CardContent, Typography, Grid, FormControl, InputLabel,
  Select, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Divider, Alert,
} from '@mui/material'
import CloudIcon from '@mui/icons-material/Cloud'
import FolderIcon from '@mui/icons-material/Folder'
import StreamIcon from '@mui/icons-material/Stream'
import PackageIcon from '@mui/icons-material/Inventory'

const OUTPUT_TYPES = [
  { value: 'HLS', label: 'HLS' },
  { value: 'RTMP', label: 'RTMP Re-stream' },
]
const DESTINATIONS = [
  { value: 'S3', label: 'Amazon S3', icon: <CloudIcon fontSize="small" /> },
  { value: 'LOCAL', label: 'Local Directory', icon: <FolderIcon fontSize="small" /> },
  { value: 'MEDIAPACKAGE', label: 'MediaPackage', icon: <PackageIcon fontSize="small" /> },
]
const PRESETS = [
  { value: 'ultrafast', label: 'Ultra Fast (Lowest Latency)' },
  { value: 'superfast', label: 'Super Fast' },
  { value: 'veryfast', label: 'Very Fast (Recommended for Live)' },
  { value: 'faster', label: 'Faster' },
  { value: 'fast', label: 'Fast' },
  { value: 'medium', label: 'Medium' },
]

export default function LiveOutputSection({ value, onChange }) {
  const set = (field, val) => onChange({ ...value, [field]: val })
  const isHLS = (value.output_type || 'HLS') === 'HLS'
  const isRTMP = value.output_type === 'RTMP'
  const dest = value.output_destination || 'LOCAL'

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box component="span" sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: 'error.main', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>2</Box>
          Output Configuration
        </Typography>

        {/* Output Type */}
        <Box sx={{ mb: 2.5 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Output Format</Typography>
          <ToggleButtonGroup
            value={value.output_type || 'HLS'}
            exclusive onChange={(_, v) => v && set('output_type', v)}
            size="small"
          >
            {OUTPUT_TYPES.map((t) => (
              <ToggleButton key={t.value} value={t.value} sx={{ gap: 0.5, px: 2 }}>
                <StreamIcon fontSize="small" /> {t.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        {/* RTMP Output */}
        {isRTMP && (
          <Box sx={{ mb: 2.5 }}>
            <TextField
              fullWidth size="small" label="RTMP Output URL *"
              placeholder="rtmp://live.twitch.tv/live/your-stream-key"
              value={value.rtmp_output_url || ''}
              onChange={(e) => set('rtmp_output_url', e.target.value)}
            />
          </Box>
        )}

        {/* HLS Destination */}
        {isHLS && (
          <>
            <Box sx={{ mb: 2.5 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Destination</Typography>
              <ToggleButtonGroup
                value={dest} exclusive onChange={(_, v) => v && set('output_destination', v)} size="small"
              >
                {DESTINATIONS.map((d) => (
                  <ToggleButton key={d.value} value={d.value} sx={{ gap: 0.5, px: 2 }}>
                    {d.icon} {d.label}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Box>

            {dest === 'S3' && (
              <Box sx={{ mb: 2.5, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
                <Typography variant="subtitle2" sx={{ mb: 1.5 }}>S3 Configuration</Typography>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={4}>
                    <TextField fullWidth size="small" label="S3 Bucket *" value={value.s3_bucket || ''} onChange={(e) => set('s3_bucket', e.target.value)} />
                  </Grid>
                  <Grid item xs={12} md={4}>
                    <TextField fullWidth size="small" label="S3 Path Prefix" value={value.s3_path || ''} onChange={(e) => set('s3_path', e.target.value)} placeholder="live/channel-name" />
                  </Grid>
                  <Grid item xs={12} md={4}>
                    <TextField fullWidth size="small" label="CloudFront Domain" value={value.s3_cloudfront_domain || ''} onChange={(e) => set('s3_cloudfront_domain', e.target.value)} placeholder="https://d1234.cloudfront.net" />
                  </Grid>
                </Grid>
              </Box>
            )}

            {dest === 'LOCAL' && (
              <Box sx={{ mb: 2.5 }}>
                <TextField fullWidth size="small" label="Local Output Directory *" value={value.local_path || ''} onChange={(e) => set('local_path', e.target.value)} placeholder="/var/www/html/live/channel" />
              </Box>
            )}

            {dest === 'MEDIAPACKAGE' && (
              <Box sx={{ mb: 2.5, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
                <Typography variant="subtitle2" sx={{ mb: 1.5 }}>AWS MediaPackage Configuration</Typography>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <TextField fullWidth size="small" label="MediaPackage Ingest URL *" value={value.mediapackage_url || ''} onChange={(e) => set('mediapackage_url', e.target.value)} placeholder="https://abc123.mediapackage.us-east-1.amazonaws.com/in/v2/..." />
                  </Grid>
                  <Grid item xs={12} md={3}>
                    <TextField fullWidth size="small" label="Ingest Username" value={value.mediapackage_user || ''} onChange={(e) => set('mediapackage_user', e.target.value)} />
                  </Grid>
                  <Grid item xs={12} md={3}>
                    <TextField fullWidth size="small" type="password" label="Ingest Password" value={value.mediapackage_password || ''} onChange={(e) => set('mediapackage_password', e.target.value)} />
                  </Grid>
                </Grid>
              </Box>
            )}

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2" sx={{ mb: 1.5 }}>Live HLS Settings</Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={3}>
                <TextField fullWidth size="small" label="Master Filename" value={value.master_filename || 'live'} onChange={(e) => set('master_filename', e.target.value)} helperText="Without .m3u8" />
              </Grid>
              <Grid item xs={12} md={2}>
                <TextField fullWidth size="small" type="number" label="Segment Length (s)" value={value.segment_length || 4} onChange={(e) => set('segment_length', parseInt(e.target.value) || 4)} inputProps={{ min: 1, max: 30 }} />
              </Grid>
              <Grid item xs={12} md={2}>
                <TextField fullWidth size="small" type="number" label="Playlist Size" value={value.hls_list_size || 6} onChange={(e) => set('hls_list_size', parseInt(e.target.value) || 6)} helperText="Segments in window" inputProps={{ min: 1 }} />
              </Grid>
              <Grid item xs={12} md={5}>
                <FormControl fullWidth size="small">
                  <InputLabel>HLS Flags</InputLabel>
                  <Select value={value.hls_flags || 'delete_segments+append_list'} label="HLS Flags" onChange={(e) => set('hls_flags', e.target.value)}>
                    <MenuItem value="delete_segments+append_list">delete_segments + append_list (Live)</MenuItem>
                    <MenuItem value="delete_segments">delete_segments</MenuItem>
                    <MenuItem value="append_list">append_list</MenuItem>
                    <MenuItem value="independent_segments">independent_segments (DVR)</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </>
        )}

        <Divider sx={{ my: 2 }} />

        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Encoder Preset</Typography>
          <FormControl size="small" sx={{ minWidth: 240 }}>
            <InputLabel>Preset</InputLabel>
            <Select value={value.preset || 'veryfast'} label="Preset" onChange={(e) => set('preset', e.target.value)}>
              {PRESETS.map((p) => <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>)}
            </Select>
          </FormControl>
          <Alert severity="info" sx={{ mt: 1, py: 0.5 }}>
            For live streaming, use ultrafast or veryfast preset to minimize encoding latency.
          </Alert>
        </Box>
      </CardContent>
    </Card>
  )
}

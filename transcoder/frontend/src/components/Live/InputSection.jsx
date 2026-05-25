import React, { useState } from 'react'
import {
  Box, Card, CardContent, Typography, Grid, FormControl, InputLabel,
  Select, MenuItem, TextField, Button, Alert, CircularProgress, Chip,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import LiveTvIcon from '@mui/icons-material/LiveTv'
import { validateLiveInput } from '../../api/transcoder'

const INPUT_TYPES = [
  { value: 'RTMP', label: 'RTMP (rtmp://)' },
  { value: 'SRT', label: 'SRT (srt://)' },
  { value: 'HLS', label: 'HLS Stream (.m3u8)' },
  { value: 'HTTP', label: 'HTTP(S) URL' },
  { value: 'FILE', label: 'File (MP4/MOV)' },
]

const PLACEHOLDERS = {
  RTMP: 'rtmp://live.example.com/app/stream-key',
  SRT: 'srt://live.example.com:9000?streamid=your-key',
  HLS: 'https://live.example.com/stream/master.m3u8',
  HTTP: 'https://live.example.com/stream.ts',
  FILE: '/path/to/file.mp4 or https://example.com/video.mp4',
}

function ProbeResult({ info }) {
  if (!info) return null
  const video = info.video?.[0] || {}
  const audio = info.audio?.[0] || {}
  return (
    <Box sx={{ mt: 1.5, p: 1.5, bgcolor: 'rgba(0,200,150,0.07)', borderRadius: 1, border: '1px solid rgba(0,200,150,0.2)' }}>
      <Typography variant="caption" sx={{ fontWeight: 700, color: 'secondary.main', display: 'block', mb: 0.5 }}>Stream Analysis</Typography>
      <Grid container spacing={1}>
        {video.codec && <Grid item xs={6}><InfoLine label="Video" value={`${video.codec} ${video.width || ''}×${video.height || ''}`} /></Grid>}
        {video.fps && <Grid item xs={6}><InfoLine label="FPS" value={video.fps} /></Grid>}
        {audio.codec && <Grid item xs={6}><InfoLine label="Audio" value={`${audio.codec} ${audio.channels || ''}ch`} /></Grid>}
        {audio.sample_rate && <Grid item xs={6}><InfoLine label="Sample Rate" value={`${audio.sample_rate} Hz`} /></Grid>}
      </Grid>
    </Box>
  )
}
function InfoLine({ label, value }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}: </Typography>
      <Typography variant="caption" fontWeight={600}>{value}</Typography>
    </Box>
  )
}

export default function LiveInputSection({ value, onChange }) {
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState(null)

  const set = (field, val) => {
    onChange({ ...value, [field]: val })
    if (field === 'input_url') setValidation(null)
  }

  const handleValidate = async () => {
    if (!value.input_url?.trim()) return
    setValidating(true)
    setValidation(null)
    try {
      const res = await validateLiveInput(value.input_url)
      setValidation(res)
    } catch (e) {
      setValidation({ valid: false, message: e.message })
    } finally {
      setValidating(false)
    }
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box component="span" sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: 'error.main', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>1</Box>
          <LiveTvIcon fontSize="small" color="error" />
          Live Input Configuration
        </Typography>

        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={12}>
            <TextField
              fullWidth size="small" label="Channel Name *"
              placeholder="e.g. Live-News-Channel or Samsung-TVPlus-LIVE"
              value={value.channel_name || ''}
              onChange={(e) => set('channel_name', e.target.value)}
              helperText="Unique identifier for this live channel (used in the Jobs table)"
            />
          </Grid>
        </Grid>

        <Grid container spacing={2}>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Input Type</InputLabel>
              <Select value={value.input_type || 'RTMP'} label="Input Type" onChange={(e) => set('input_type', e.target.value)}>
                {INPUT_TYPES.map((t) => <MenuItem key={t.value} value={t.value}>{t.label}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={7}>
            <TextField
              fullWidth size="small" label="Live Input URL *"
              placeholder={PLACEHOLDERS[value.input_type] || 'Enter live input URL'}
              value={value.input_url || ''}
              onChange={(e) => set('input_url', e.target.value)}
            />
          </Grid>

          <Grid item xs={12} md={2}>
            <Button
              fullWidth variant="outlined" size="small" sx={{ height: 40 }}
              onClick={handleValidate}
              disabled={validating || !value.input_url?.trim()}
              startIcon={validating ? <CircularProgress size={14} /> : <PlayArrowIcon />}
            >
              {validating ? 'Checking...' : 'Validate'}
            </Button>
          </Grid>
        </Grid>

        {validation && (
          <Alert
            severity={validation.valid ? 'success' : 'error'}
            icon={validation.valid ? <CheckCircleIcon /> : <ErrorIcon />}
            sx={{ mt: 1.5, py: 0.5 }}
          >
            {validation.message}
          </Alert>
        )}

        {validation?.probe && <ProbeResult info={validation.probe} />}

        {value.input_type === 'RTMP' && (
          <Alert severity="info" sx={{ mt: 1.5 }}>
            For RTMP inputs, ensure your encoder is already streaming before starting the live channel.
          </Alert>
        )}
        {value.input_type === 'SRT' && (
          <Alert severity="info" sx={{ mt: 1.5 }}>
            SRT provides reliable, low-latency streaming. Ensure firewall allows UDP on the specified port.
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

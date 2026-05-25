import React, { useState } from 'react'
import {
  Box, Card, CardContent, Typography, Grid, FormControl, InputLabel,
  Select, MenuItem, TextField, Button, IconButton, Chip, Alert,
  CircularProgress, Divider, Tooltip, Stack,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import SubtitlesIcon from '@mui/icons-material/Subtitles'
import { validateVodInput } from '../../api/transcoder'

const INPUT_TYPES = [
  { value: 'FILE', label: 'File (MP4/MOV/MXF)' },
  { value: 'HLS', label: 'HLS Stream (.m3u8)' },
  { value: 'HTTP', label: 'HTTP(S) URL' },
  { value: 'S3', label: 'Amazon S3' },
]

const SUBTITLE_LANGS = [
  { value: 'en', label: 'English' }, { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' }, { value: 'de', label: 'German' },
  { value: 'pt', label: 'Portuguese' }, { value: 'ja', label: 'Japanese' },
  { value: 'ko', label: 'Korean' }, { value: 'zh', label: 'Chinese' },
]

function ProbeResult({ info }) {
  if (!info) return null
  const fmt = info.format || {}
  const video = info.video?.[0] || {}
  const audio = info.audio?.[0] || {}
  return (
    <Box sx={{ mt: 1.5, p: 1.5, bgcolor: 'rgba(0,200,150,0.07)', borderRadius: 1, border: '1px solid rgba(0,200,150,0.2)' }}>
      <Typography variant="caption" sx={{ fontWeight: 700, color: 'secondary.main', display: 'block', mb: 0.5 }}>
        Input Analysis
      </Typography>
      <Grid container spacing={1}>
        {fmt.container && <Grid item xs={4}><InfoChip label="Format" value={fmt.container.split(' ').slice(-1)[0]} /></Grid>}
        {fmt.duration && <Grid item xs={4}><InfoChip label="Duration" value={`${Math.floor(fmt.duration / 60)}m ${(fmt.duration % 60).toFixed(0)}s`} /></Grid>}
        {fmt.size_mb && <Grid item xs={4}><InfoChip label="Size" value={`${fmt.size_mb} MB`} /></Grid>}
        {video.codec && <Grid item xs={4}><InfoChip label="Video" value={`${video.codec} ${video.width}×${video.height}`} /></Grid>}
        {video.fps && <Grid item xs={4}><InfoChip label="FPS" value={video.fps.split('/').reduce((a, b) => (a / b).toFixed(2))} /></Grid>}
        {audio.codec && <Grid item xs={4}><InfoChip label="Audio" value={`${audio.codec} ${audio.channels}ch`} /></Grid>}
      </Grid>
    </Box>
  )
}

function InfoChip({ label, value }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}: </Typography>
      <Typography variant="caption" sx={{ fontWeight: 600 }}>{value}</Typography>
    </Box>
  )
}

export default function InputSection({ value, onChange }) {
  const [validating, setValidating] = useState(false)
  const [validationResult, setValidationResult] = useState(null)
  const [addingClip, setAddingClip] = useState(false)
  const [clipForm, setClipForm] = useState({ start_timecode: '', end_timecode: '' })
  const [clipError, setClipError] = useState('')

  const handleChange = (field, val) => {
    onChange({ ...value, [field]: val })
    if (field === 'input_url') setValidationResult(null)
  }

  const handleValidate = async () => {
    if (!value.input_url?.trim()) return
    setValidating(true)
    setValidationResult(null)
    try {
      const result = await validateVodInput(value.input_url)
      setValidationResult(result)
      if (result.probe) onChange({ ...value, _probeInfo: result.probe })
    } catch (e) {
      setValidationResult({ valid: false, message: e.message })
    } finally {
      setValidating(false)
    }
  }

  const addClip = () => {
    setClipError('')
    const tc = /^\d{2}:\d{2}:\d{2}:\d{2}$/
    if (!tc.test(clipForm.start_timecode)) { setClipError('Start timecode must be HH:MM:SS:FF'); return }
    if (!tc.test(clipForm.end_timecode)) { setClipError('End timecode must be HH:MM:SS:FF'); return }
    const clips = [...(value.clips || []), { ...clipForm }]
    onChange({ ...value, clips })
    setClipForm({ start_timecode: '', end_timecode: '' })
    setAddingClip(false)
  }

  const removeClip = (idx) => {
    const clips = (value.clips || []).filter((_, i) => i !== idx)
    onChange({ ...value, clips })
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box component="span" sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: 'primary.main', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>1</Box>
          Input Configuration
        </Typography>

        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={12}>
            <TextField
              fullWidth size="small" label="Channel Name *"
              placeholder="e.g. Samsung-TV-Plus-EN or My-VOD-Channel"
              value={value.channel_name || ''}
              onChange={(e) => handleChange('channel_name', e.target.value)}
              helperText="Unique identifier for this channel/job (used in the Jobs table)"
            />
          </Grid>
        </Grid>

        <Grid container spacing={2}>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Input Type</InputLabel>
              <Select value={value.input_type || 'FILE'} label="Input Type" onChange={(e) => handleChange('input_type', e.target.value)}>
                {INPUT_TYPES.map((t) => <MenuItem key={t.value} value={t.value}>{t.label}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={7}>
            <TextField
              fullWidth size="small" label="Input URL / Path *"
              placeholder="https://example.com/video.mp4 or /local/path/video.mp4 or s3://bucket/key"
              value={value.input_url || ''}
              onChange={(e) => handleChange('input_url', e.target.value)}
              error={!!value._urlError}
              helperText={value._urlError}
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

        {validationResult && (
          <Alert
            severity={validationResult.valid ? 'success' : 'error'}
            icon={validationResult.valid ? <CheckCircleIcon /> : <ErrorIcon />}
            sx={{ mt: 1.5, py: 0.5 }}
          >
            {validationResult.message}
          </Alert>
        )}

        {validationResult?.probe && <ProbeResult info={validationResult.probe} />}

        <Divider sx={{ my: 2 }} />

        {/* Input Clipping */}
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="subtitle2">Input Clipping (Optional)</Typography>
            <Button size="small" startIcon={<AddIcon />} onClick={() => setAddingClip(true)}>
              Add Clip
            </Button>
          </Box>

          {(value.clips || []).length === 0 && !addingClip && (
            <Typography variant="caption" color="text.secondary">
              No clips defined — entire input will be transcoded
            </Typography>
          )}

          <Stack spacing={1}>
            {(value.clips || []).map((clip, i) => (
              <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1, bgcolor: 'background.default', borderRadius: 1 }}>
                <Typography variant="caption" sx={{ flex: 1 }}>
                  Clip {i + 1}: <strong>{clip.start_timecode}</strong> → <strong>{clip.end_timecode}</strong>
                </Typography>
                <IconButton size="small" color="error" onClick={() => removeClip(i)}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
          </Stack>

          {addingClip && (
            <Box sx={{ mt: 1.5, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
              <Grid container spacing={2} alignItems="center">
                <Grid item xs={12} md={4}>
                  <TextField
                    fullWidth size="small" label="Start Timecode (HH:MM:SS:FF)"
                    placeholder="00:01:00:00"
                    value={clipForm.start_timecode}
                    onChange={(e) => setClipForm({ ...clipForm, start_timecode: e.target.value })}
                  />
                </Grid>
                <Grid item xs={12} md={4}>
                  <TextField
                    fullWidth size="small" label="End Timecode (HH:MM:SS:FF)"
                    placeholder="00:05:00:00"
                    value={clipForm.end_timecode}
                    onChange={(e) => setClipForm({ ...clipForm, end_timecode: e.target.value })}
                  />
                </Grid>
                <Grid item xs={6} md={2}>
                  <Button fullWidth size="small" variant="contained" onClick={addClip}>Add</Button>
                </Grid>
                <Grid item xs={6} md={2}>
                  <Button fullWidth size="small" variant="outlined" onClick={() => { setAddingClip(false); setClipError('') }}>Cancel</Button>
                </Grid>
              </Grid>
              {clipError && <Alert severity="error" sx={{ mt: 1, py: 0.5 }}>{clipError}</Alert>}
            </Box>
          )}
        </Box>

        <Divider sx={{ my: 2 }} />

        {/* Subtitle Input */}
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <SubtitlesIcon fontSize="small" /> Subtitle File (Optional)
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} md={8}>
              <TextField
                fullWidth size="small" label="Subtitle URL / Path (.srt or .vtt)"
                placeholder="https://example.com/subs.srt or /local/subs.vtt"
                value={value.subtitle_url || ''}
                onChange={(e) => handleChange('subtitle_url', e.target.value)}
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <FormControl fullWidth size="small">
                <InputLabel>Language</InputLabel>
                <Select value={value.subtitle_language || 'en'} label="Language" onChange={(e) => handleChange('subtitle_language', e.target.value)}>
                  {SUBTITLE_LANGS.map((l) => <MenuItem key={l.value} value={l.value}>{l.label}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
        </Box>
      </CardContent>
    </Card>
  )
}

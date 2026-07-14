import React, { useState, useEffect } from 'react'
import {
  Box, Card, CardContent, Typography, Grid, FormControl, InputLabel,
  Select, MenuItem, TextField, Button, IconButton, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Paper, Alert,
  Chip,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import SaveIcon from '@mui/icons-material/Save'
import CancelIcon from '@mui/icons-material/Cancel'
import { getTemplates, getAv1Encoders } from '../../api/transcoder'
import { isAv1, av1Meta, clampAv1Preset, availableAv1Libraries, pickAv1Default } from '../shared/av1'

const VIDEO_CODECS = [
  { value: 'libx264', label: 'H.264 (AVC)' },
  { value: 'libx265', label: 'H.265 (HEVC)' },
  { value: 'av1', label: 'AV1 (royalty-free)' },
]
const AUDIO_CODECS = [
  { value: 'aac', label: 'AAC' },
  { value: 'mp2', label: 'MP2' },
  { value: 'ac3', label: 'Dolby AC-3' },
]
const RESOLUTIONS = [
  { value: '1920x1080', label: 'FHD (1920×1080)' },
  { value: '1280x720', label: 'HD (1280×720)' },
  { value: '960x540', label: 'qHD (960×540)' },
  { value: '640x360', label: 'SD (640×360)' },
  { value: '426x240', label: '240p (426×240)' },
]

const DEFAULT_VARIANT = {
  resolution: '1280x720',
  video_codec: 'libx264',
  video_bitrate: 2000000,
  framerate: '30',
  gop: 60,
  reference_frames: 2,
  profile: 'main',
  level: '4.1',
  audio_codec: 'aac',
  audio_bitrate: 128000,
  sample_rate: 48000,
}

function variantToPayload(v) {
  const [width, height] = (v.resolution || '1280x720').split('x').map(Number)
  return { ...v, width, height }
}

function formatBitrate(bps) {
  return bps >= 1000000 ? `${(bps / 1000000).toFixed(1)} Mbps` : `${(bps / 1000).toFixed(0)} kbps`
}

export default function LiveVideoAudioConfig({ value: variants = [], onChange }) {
  const [templates, setTemplates] = useState({})
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [addForm, setAddForm] = useState(null)
  const [editing, setEditing] = useState(null)
  const [editIdx, setEditIdx] = useState(-1)
  const [av1Info, setAv1Info] = useState(null)

  useEffect(() => {
    getTemplates().then(setTemplates).catch(() => {})
    getAv1Encoders().then(setAv1Info).catch(() => {})
  }, [])

  const av1Available = av1Info?.available ?? null
  const av1Libs = availableAv1Libraries(av1Available)
  const av1Disabled = Array.isArray(av1Available) && av1Available.length === 0

  const applyTemplate = (key) => {
    if (!key || !templates[key]) return
    const tmplVariants = templates[key].variants.map((v) => ({ ...v, resolution: `${v.width}x${v.height}` }))
    onChange(tmplVariants)
    setSelectedTemplate(key)
  }

  const renderForm = (form, setForm, onSave, onCancel) => (
    <Box sx={{ p: 2, bgcolor: 'background.default', borderRadius: 1, mt: 1 }}>
      <Grid container spacing={2}>
        <Grid item xs={6} md={3}>
          <FormControl fullWidth size="small">
            <InputLabel>Resolution</InputLabel>
            <Select value={form.resolution || '1280x720'} label="Resolution" onChange={(e) => setForm({ ...form, resolution: e.target.value })}>
              {RESOLUTIONS.map((r) => <MenuItem key={r.value} value={r.value}>{r.label}</MenuItem>)}
            </Select>
          </FormControl>
        </Grid>
        <Grid item xs={6} md={3}>
          <FormControl fullWidth size="small">
            <InputLabel>Video Codec</InputLabel>
            <Select
              value={isAv1(form.video_codec) ? 'av1' : (form.video_codec || 'libx264')}
              label="Video Codec"
              onChange={(e) => {
                const val = e.target.value
                if (val === 'av1') { const d = pickAv1Default(av1Info) || 'libsvtav1'; setForm({ ...form, video_codec: d, av1_preset: av1Meta(d).default, av1_segment_ext: form.av1_segment_ext ?? 'm4s' }) }
                else { const { av1_preset, ...rest } = form; setForm({ ...rest, video_codec: val }) }
              }}
            >
              {VIDEO_CODECS.map((c) => (
                <MenuItem key={c.value} value={c.value} disabled={c.value === 'av1' && av1Disabled}>
                  {c.label}{c.value === 'av1' && av1Disabled ? ' — not available on server' : ''}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Grid>
        {isAv1(form.video_codec) && (
          <>
            <Grid item xs={6} md={3}>
              <FormControl fullWidth size="small">
                <InputLabel>AV1 Library</InputLabel>
                <Select
                  value={form.video_codec}
                  label="AV1 Library"
                  onChange={(e) => {
                    const lib = e.target.value
                    setForm({ ...form, video_codec: lib, av1_preset: clampAv1Preset(lib, form.av1_preset ?? av1Meta(lib).default) })
                  }}
                >
                  {av1Libs.map((l) => <MenuItem key={l.value} value={l.value}>{l.label}</MenuItem>)}
                  {av1Available && !av1Available.includes(form.video_codec) && (
                    <MenuItem value={form.video_codec}>{av1Meta(form.video_codec).label} (unavailable)</MenuItem>
                  )}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6} md={3}>
              <FormControl fullWidth size="small">
                <InputLabel>AV1 Preset (speed)</InputLabel>
                <Select
                  value={form.av1_preset ?? av1Meta(form.video_codec).default}
                  label="AV1 Preset (speed)"
                  onChange={(e) => setForm({ ...form, av1_preset: e.target.value })}
                >
                  {Array.from({ length: av1Meta(form.video_codec).max + 1 }, (_, n) => (
                    <MenuItem key={n} value={n}>{n}{n === 0 ? ' (slowest / best)' : n === av1Meta(form.video_codec).max ? ' (fastest)' : ''}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6} md={3}>
              <FormControl fullWidth size="small">
                <InputLabel>AV1 Segment Container</InputLabel>
                <Select
                  value={form.av1_segment_ext || 'm4s'}
                  label="AV1 Segment Container"
                  onChange={(e) => setForm({ ...form, av1_segment_ext: e.target.value })}
                >
                  <MenuItem value="m4s">.m4s (fMP4 / CMAF)</MenuItem>
                  <MenuItem value="mp4">.mp4 (fMP4)</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              {av1Available && !av1Available.includes(form.video_codec) ? (
                <Alert severity="warning" sx={{ py: 0.5, '& .MuiAlert-message': { fontSize: 12 } }}>
                  {av1Meta(form.video_codec).label} is not available in this server's FFmpeg build
                  {av1Available.length ? ` (available: ${av1Available.join(', ')})` : ''}. Pick an available library or the channel will be rejected.
                </Alert>
              ) : (
                <Alert severity="info" sx={{ py: 0.5, '& .MuiAlert-message': { fontSize: 12 } }}>
                  {av1Meta(form.video_codec).hint} For live, higher presets keep latency low.
                </Alert>
              )}
            </Grid>
          </>
        )}
        <Grid item xs={6} md={3}>
          <TextField fullWidth size="small" type="number" label="Video Bitrate (bps)" value={form.video_bitrate || ''} onChange={(e) => setForm({ ...form, video_bitrate: parseInt(e.target.value) || 0 })} helperText={form.video_bitrate ? formatBitrate(form.video_bitrate) : ''} />
        </Grid>
        <Grid item xs={6} md={3}>
          <TextField fullWidth size="small" label="Framerate" value={form.framerate || '30'} onChange={(e) => setForm({ ...form, framerate: e.target.value })} />
        </Grid>
        <Grid item xs={6} md={3}>
          <TextField fullWidth size="small" type="number" label="GOP" value={form.gop || 60} onChange={(e) => setForm({ ...form, gop: parseInt(e.target.value) || 60 })} />
        </Grid>
        <Grid item xs={6} md={3}>
          <FormControl fullWidth size="small">
            <InputLabel>Audio Codec</InputLabel>
            <Select value={form.audio_codec || 'aac'} label="Audio Codec" onChange={(e) => setForm({ ...form, audio_codec: e.target.value })}>
              {AUDIO_CODECS.map((c) => <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>)}
            </Select>
          </FormControl>
        </Grid>
        <Grid item xs={6} md={3}>
          <TextField fullWidth size="small" type="number" label="Audio Bitrate (bps)" value={form.audio_bitrate || 128000} onChange={(e) => setForm({ ...form, audio_bitrate: parseInt(e.target.value) || 128000 })} />
        </Grid>
        <Grid item xs={6} md={3}>
          <FormControl fullWidth size="small">
            <InputLabel>Sample Rate</InputLabel>
            <Select value={form.sample_rate || 48000} label="Sample Rate" onChange={(e) => setForm({ ...form, sample_rate: e.target.value })}>
              <MenuItem value={44100}>44100 Hz</MenuItem>
              <MenuItem value={48000}>48000 Hz</MenuItem>
            </Select>
          </FormControl>
        </Grid>
      </Grid>
      <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
        <Button size="small" variant="contained" startIcon={<SaveIcon />} onClick={onSave}>Save</Button>
        <Button size="small" variant="outlined" startIcon={<CancelIcon />} onClick={onCancel}>Cancel</Button>
      </Box>
    </Box>
  )

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box component="span" sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: 'error.main', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>3</Box>
          Video & Audio Configuration
        </Typography>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel>Quick Template</InputLabel>
            <Select value={selectedTemplate} label="Quick Template" onChange={(e) => applyTemplate(e.target.value)}>
              <MenuItem value="">— Select Template —</MenuItem>
              {Object.entries(templates).map(([key, tmpl]) => (
                <MenuItem key={key} value={key}>{tmpl.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {selectedTemplate && <Chip label="Template applied" color="secondary" size="small" onDelete={() => { setSelectedTemplate(''); onChange([]) }} />}
          <Box sx={{ flex: 1 }} />
          <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={() => setAddForm({ ...DEFAULT_VARIANT })} disabled={!!addForm}>Add Variant</Button>
        </Box>

        {variants.length > 0 && (
          <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
            <Table size="small">
              <TableHead>
                <TableRow sx={{ '& th': { fontWeight: 700, bgcolor: 'rgba(244,67,54,0.12)', fontSize: 11 } }}>
                  {['Resolution', 'Video Codec', 'Video Bitrate', 'FPS', 'GOP', 'Audio Codec', 'Audio Bitrate', ''].map((h) => <TableCell key={h}>{h}</TableCell>)}
                </TableRow>
              </TableHead>
              <TableBody>
                {variants.map((v, i) => (
                  <TableRow key={i}>
                    <TableCell>{v.width || v.resolution?.split('x')[0]}×{v.height || v.resolution?.split('x')[1]}</TableCell>
                    <TableCell><Chip label={v.video_codec} size="small" variant="outlined" /></TableCell>
                    <TableCell>{formatBitrate(v.video_bitrate)}</TableCell>
                    <TableCell>{v.framerate}</TableCell>
                    <TableCell>{v.gop}</TableCell>
                    <TableCell>{v.audio_codec}</TableCell>
                    <TableCell>{v.audio_bitrate / 1000}k</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.5 }}>
                        <IconButton size="small" onClick={() => { setEditing({ ...v, resolution: v.resolution || `${v.width}x${v.height}` }); setEditIdx(i) }}><EditIcon fontSize="small" /></IconButton>
                        <IconButton size="small" color="error" onClick={() => onChange(variants.filter((_, idx) => idx !== i))}><DeleteIcon fontSize="small" /></IconButton>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {variants.length === 0 && !addForm && <Alert severity="info">Select a template or add variants manually</Alert>}

        {addForm && renderForm(addForm, setAddForm, () => { onChange([...variants, variantToPayload(addForm)]); setAddForm(null) }, () => setAddForm(null))}
        {editing && renderForm(editing, setEditing, () => { const u = [...variants]; u[editIdx] = variantToPayload(editing); onChange(u); setEditing(null); setEditIdx(-1) }, () => { setEditing(null); setEditIdx(-1) })}
      </CardContent>
    </Card>
  )
}

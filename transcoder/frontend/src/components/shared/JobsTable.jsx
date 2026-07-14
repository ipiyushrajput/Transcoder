import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box, Card, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, IconButton,
  Button, TextField, Select, MenuItem, FormControl, InputLabel,
  Dialog, DialogTitle, DialogContent, DialogActions, Tooltip,
  Alert, CircularProgress, Pagination, Stack, LinearProgress,
  Divider, Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import DeleteIcon from '@mui/icons-material/Delete'
import InfoIcon from '@mui/icons-material/Info'
import StopIcon from '@mui/icons-material/Stop'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import FileCopyIcon from '@mui/icons-material/FileCopy'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { listJobs, getJob, getJobLogs, deleteJob, stopVodJob, stopLiveChannel } from '../../api/transcoder'

const STATUS_COLORS = {
  RUNNING: 'success',
  COMPLETED: 'info',
  FAILED: 'error',
  STOPPED: 'warning',
  PENDING: 'default',
}

function secsToHMS(totalSecs) {
  const s = Math.round(totalSecs)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function LogsDialog({ open, jobId, jobStatus, onClose }) {
  const [logs, setLogs] = useState('')
  const [loading, setLoading] = useState(false)
  const intervalRef = useRef(null)
  const bottomRef = useRef(null)

  const fetchLogs = useCallback(async () => {
    if (!jobId) return
    try {
      const d = await getJobLogs(jobId, 300)
      setLogs(d.logs || 'No logs available')
    } catch {
      setLogs('Failed to load logs')
    }
  }, [jobId])

  useEffect(() => {
    if (!open || !jobId) return
    setLoading(true)
    fetchLogs().finally(() => setLoading(false))
    if (jobStatus === 'RUNNING') {
      intervalRef.current = setInterval(fetchLogs, 10000)
    }
    return () => clearInterval(intervalRef.current)
  }, [open, jobId, jobStatus, fetchLogs])

  useEffect(() => {
    if (jobStatus !== 'RUNNING') clearInterval(intervalRef.current)
  }, [jobStatus])

  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        FFmpeg Logs — {jobId?.slice(0, 8)}
        <Chip label={jobStatus} color={STATUS_COLORS[jobStatus] || 'default'} size="small" sx={{ ml: 1 }} />
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={fetchLogs}><RefreshIcon fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
        ) : (
          <Box component="pre" sx={{ fontSize: 11, bgcolor: '#0d1117', color: '#e6edf3', p: 2, borderRadius: 1, overflow: 'auto', maxHeight: 500, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace' }}>
            {logs || 'No logs found for this job.'}
            <div ref={bottomRef} />
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1, ml: 1 }}>
          {jobStatus === 'RUNNING' ? 'Auto-refreshing every 10s' : 'Showing last 300 lines'}
        </Typography>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

function SectionHeader({ children }) {
  return (
    <Typography variant="subtitle2" sx={{ mt: 2, mb: 1, color: 'primary.main', fontWeight: 700, textTransform: 'uppercase', fontSize: 11, letterSpacing: 0.5 }}>
      {children}
    </Typography>
  )
}

function DetailRow({ label, value, mono }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <Box sx={{ display: 'contents' }}>
      <Typography variant="caption" color="text.secondary" sx={{ gridColumn: '1', py: 0.4 }}>{label}</Typography>
      <Typography variant="body2" sx={{ gridColumn: '2', py: 0.4, wordBreak: 'break-all', fontFamily: mono ? 'monospace' : 'inherit', fontSize: mono ? 11 : 'inherit' }}>
        {String(value)}
      </Typography>
    </Box>
  )
}

function DetailsGrid({ children }) {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: '2px 12px', alignItems: 'start' }}>
      {children}
    </Box>
  )
}

function JobDetailDialog({ open, jobId, onClose }) {
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open || !jobId) return
    setLoading(true)
    getJob(jobId).then(setJob).catch(() => setJob(null)).finally(() => setLoading(false))
  }, [open, jobId])

  const handleCopyConfig = () => {
    if (!job) return
    const config = buildCopyConfig(job)
    navigator.clipboard.writeText(JSON.stringify(config, null, 2)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box sx={{ flex: 1 }}>
          Job Details — <span style={{ fontWeight: 400, fontSize: 14 }}>{job?.name || jobId?.slice(0, 8)}</span>
        </Box>
        <Tooltip title={copied ? 'Copied!' : 'Copy full config as JSON'}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={handleCopyConfig} disabled={!job} color={copied ? 'success' : 'primary'} sx={{ fontSize: 12 }}>
            {copied ? 'Copied!' : 'Copy Config'}
          </Button>
        </Tooltip>
      </DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
        ) : job ? (
          <Stack spacing={0.5} sx={{ pt: 0.5 }}>
            {/* Status */}
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1 }}>
              <Chip label={job.type} size="small" variant="outlined" color={job.type === 'LIVE' ? 'error' : 'primary'} />
              <Chip label={job.status} size="small" color={STATUS_COLORS[job.status] || 'default'} />
            </Box>

            <SectionHeader>Job Info</SectionHeader>
            <DetailsGrid>
              <DetailRow label="Channel Name" value={job.name} />
              <DetailRow label="Job ID" value={job.job_id} mono />
              <DetailRow label="Started" value={job.started_at} />
              <DetailRow label="Completed" value={job.completed_at} />
              <DetailRow label="Created" value={job.created_at} />
            </DetailsGrid>

            <Divider sx={{ my: 1 }} />
            <SectionHeader>Input Configuration</SectionHeader>
            <DetailsGrid>
              <DetailRow label="Input Type" value={job.input_type} />
              <DetailRow label="Input URL" value={job.input_url} mono />
              <DetailRow label="Subtitle URL" value={job.subtitle_url} mono />
              <DetailRow label="Subtitle Language" value={job.subtitle_language} />
            </DetailsGrid>
            {job.clips?.length > 0 && (
              <Box sx={{ mt: 1 }}>
                <Typography variant="caption" color="text.secondary">Clips ({job.clips.length})</Typography>
                {job.clips.map((c, i) => (
                  <Typography key={i} variant="body2" sx={{ fontFamily: 'monospace', fontSize: 11 }}>
                    {i + 1}. {c.start_timecode} → {c.end_timecode}
                  </Typography>
                ))}
              </Box>
            )}

            <Divider sx={{ my: 1 }} />
            <SectionHeader>Output Configuration</SectionHeader>
            <DetailsGrid>
              <DetailRow label="Output Type" value={job.output_type} />
              <DetailRow label="Destination" value={job.output_destination} />
              <DetailRow label="Master Filename" value={job.master_filename} />
              <DetailRow label="Segment Length" value={job.segment_length ? `${job.segment_length}s` : null} />
              <DetailRow label="HLS Playlist Type" value={job.hls_playlist_type} />
              <DetailRow label="HLS Flags" value={job.hls_flags} mono />
              <DetailRow label="HLS List Size" value={job.hls_list_size} />
              <DetailRow label="Preset" value={job.preset} />
              {job.output_destination === 'S3' && <>
                <DetailRow label="S3 Bucket" value={job.s3_bucket} mono />
                <DetailRow label="S3 Path" value={job.s3_path} mono />
                <DetailRow label="CloudFront Domain" value={job.s3_cloudfront_domain} mono />
              </>}
              {job.output_destination === 'LOCAL' && (
                <DetailRow label="Local Path" value={job.local_path} mono />
              )}
              {job.output_destination === 'MEDIAPACKAGE' && <>
                <DetailRow label="MediaPackage URL" value={job.mediapackage_url} mono />
                <DetailRow label="MP User" value={job.mediapackage_user} />
              </>}
              {job.output_type === 'RTMP' && (
                <DetailRow label="RTMP Output URL" value={job.rtmp_output_url} mono />
              )}
            </DetailsGrid>

            {job.playback_url && (
              <Box sx={{ bgcolor: 'background.default', p: 1.5, borderRadius: 1, mt: 1 }}>
                <Typography variant="caption" color="text.secondary">Playback URL</Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
                  <Typography variant="body2" sx={{ flex: 1, wordBreak: 'break-all', fontSize: 11, fontFamily: 'monospace' }}>
                    {job.playback_url}
                  </Typography>
                  <IconButton size="small" onClick={() => navigator.clipboard.writeText(job.playback_url)}>
                    <ContentCopyIcon fontSize="small" />
                  </IconButton>
                </Box>
              </Box>
            )}

            {job.variants?.length > 0 && (
              <>
                <Divider sx={{ my: 1 }} />
                <SectionHeader>Video / Audio Variants ({job.variants.length})</SectionHeader>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        {['Resolution', 'V.Codec', 'V.Bitrate', 'FPS', 'GOP', 'Refs', 'Profile', 'Level', 'A.Codec', 'A.Bitrate', 'Sample Rate'].map(h => (
                          <TableCell key={h} sx={{ fontWeight: 600, fontSize: 10, p: '4px 6px' }}>{h}</TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {job.variants.map((v, i) => (
                        <TableRow key={i}>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.width}×{v.height}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>
                            {v.video_codec}{v.av1_preset != null ? ` (p${v.av1_preset})` : ''}
                          </TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.video_bitrate ? `${Math.round(v.video_bitrate / 1000)}k` : '—'}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.framerate}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.gop}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.reference_frames}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.profile}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.level}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.audio_codec}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.audio_bitrate ? `${Math.round(v.audio_bitrate / 1000)}k` : '—'}</TableCell>
                          <TableCell sx={{ fontSize: 11, p: '4px 6px' }}>{v.sample_rate}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </>
            )}

            {job.esam_enabled && (
              <>
                <Divider sx={{ my: 1 }} />
                <SectionHeader>ESAM Ad Signaling</SectionHeader>
                <DetailsGrid>
                  <DetailRow label="ESAM Enabled" value="Yes" />
                </DetailsGrid>
                {job.esam_scc_xml && (
                  <Accordion disableGutters sx={{ mt: 1, bgcolor: 'background.default' }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="caption" sx={{ fontWeight: 600 }}>SCC XML</Typography>
                    </AccordionSummary>
                    <AccordionDetails sx={{ p: 1 }}>
                      <Box component="pre" sx={{ fontSize: 10, overflow: 'auto', maxHeight: 200, m: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace' }}>
                        {job.esam_scc_xml}
                      </Box>
                    </AccordionDetails>
                  </Accordion>
                )}
                {job.esam_mcc_xml && (
                  <Accordion disableGutters sx={{ mt: 0.5, bgcolor: 'background.default' }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="caption" sx={{ fontWeight: 600 }}>MCC XML</Typography>
                    </AccordionSummary>
                    <AccordionDetails sx={{ p: 1 }}>
                      <Box component="pre" sx={{ fontSize: 10, overflow: 'auto', maxHeight: 200, m: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace' }}>
                        {job.esam_mcc_xml}
                      </Box>
                    </AccordionDetails>
                  </Accordion>
                )}
              </>
            )}

            {job.error_message && (
              <Alert severity="error" sx={{ mt: 1, fontSize: 12 }}>
                <Typography variant="caption" fontWeight={700}>Error Details:</Typography>
                <Box component="pre" sx={{ whiteSpace: 'pre-wrap', m: 0, mt: 0.5, fontSize: 11 }}>
                  {job.error_message.slice(-1000)}
                </Box>
              </Alert>
            )}
          </Stack>
        ) : <Typography color="error">Failed to load job details</Typography>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

function buildCopyConfig(job) {
  const base = {
    name: job.name,
    input_type: job.input_type,
    input_url: job.input_url,
    output_type: job.output_type,
    output_destination: job.output_destination,
    master_filename: job.master_filename,
    segment_length: job.segment_length,
    hls_playlist_type: job.hls_playlist_type,
    hls_flags: job.hls_flags,
    hls_list_size: job.hls_list_size,
    preset: job.preset,
    variants: (job.variants || []).map(v => ({
      width: v.width, height: v.height,
      video_codec: v.video_codec, video_bitrate: v.video_bitrate,
      framerate: v.framerate, gop: v.gop, reference_frames: v.reference_frames,
      profile: v.profile, level: v.level,
      audio_codec: v.audio_codec, audio_bitrate: v.audio_bitrate, sample_rate: v.sample_rate,
      av1_preset: v.av1_preset, av1_segment_ext: v.av1_segment_ext,
    })),
  }
  if (job.s3_bucket) { base.s3_bucket = job.s3_bucket; base.s3_path = job.s3_path; base.s3_cloudfront_domain = job.s3_cloudfront_domain }
  if (job.local_path) base.local_path = job.local_path
  if (job.mediapackage_url) { base.mediapackage_url = job.mediapackage_url; base.mediapackage_user = job.mediapackage_user }
  if (job.rtmp_output_url) base.rtmp_output_url = job.rtmp_output_url
  if (job.subtitle_url) { base.subtitle_url = job.subtitle_url; base.subtitle_language = job.subtitle_language }
  if (job.clips?.length) base.clips = job.clips.map(c => ({ start_timecode: c.start_timecode, end_timecode: c.end_timecode, clip_order: c.clip_order }))
  if (job.esam_enabled) { base.esam_enabled = true; base.esam_scc_xml = job.esam_scc_xml; base.esam_mcc_xml = job.esam_mcc_xml }
  return base
}

function buildVodPrefill(job) {
  return {
    input: {
      channel_name: job.name || '',
      input_type: (job.input_type || 'FILE').toUpperCase(),
      input_url: job.input_url || '',
      clips: (job.clips || []).map(c => ({ start_timecode: c.start_timecode, end_timecode: c.end_timecode, clip_order: c.clip_order })),
      subtitle_url: job.subtitle_url || '',
      subtitle_language: job.subtitle_language || 'en',
    },
    output: {
      output_type: (job.output_type || 'HLS').toUpperCase(),
      output_destination: (job.output_destination || 'LOCAL').toUpperCase(),
      s3_bucket: job.s3_bucket || '',
      s3_path: job.s3_path || '',
      s3_cloudfront_domain: job.s3_cloudfront_domain || '',
      local_path: job.local_path || '',
      master_filename: job.master_filename || 'master',
      segment_length: job.segment_length || 6,
      hls_playlist_type: job.hls_playlist_type || 'vod',
      hls_flags: job.hls_flags || 'independent_segments',
      hls_list_size: job.hls_list_size || 0,
      preset: job.preset || 'medium',
    },
    variants: (job.variants || []).map(v => ({
      width: v.width, height: v.height,
      video_codec: v.video_codec, video_bitrate: v.video_bitrate,
      framerate: v.framerate, gop: v.gop, reference_frames: v.reference_frames,
      profile: v.profile, level: v.level,
      audio_codec: v.audio_codec, audio_bitrate: v.audio_bitrate, sample_rate: v.sample_rate,
      av1_preset: v.av1_preset, av1_segment_ext: v.av1_segment_ext,
    })),
    esam: {
      esam_enabled: job.esam_enabled || false,
      esam_scc_xml: job.esam_scc_xml || '',
      esam_mcc_xml: job.esam_mcc_xml || '',
    },
  }
}

function buildLivePrefill(job) {
  return {
    input: {
      channel_name: job.name || '',
      input_type: (job.input_type || 'RTMP').toUpperCase(),
      input_url: job.input_url || '',
    },
    output: {
      output_type: (job.output_type || 'HLS').toUpperCase(),
      output_destination: (job.output_destination || 'LOCAL').toUpperCase(),
      s3_bucket: job.s3_bucket || '',
      s3_path: job.s3_path || '',
      s3_cloudfront_domain: job.s3_cloudfront_domain || '',
      local_path: job.local_path || '',
      mediapackage_url: job.mediapackage_url || '',
      mediapackage_user: job.mediapackage_user || '',
      mediapackage_password: job.mediapackage_password || '',
      rtmp_output_url: job.rtmp_output_url || '',
      master_filename: job.master_filename || 'live',
      segment_length: job.segment_length || 4,
      hls_list_size: job.hls_list_size || 6,
      hls_flags: job.hls_flags || 'delete_segments+append_list',
      preset: job.preset || 'veryfast',
    },
    variants: (job.variants || []).map(v => ({
      width: v.width, height: v.height,
      video_codec: v.video_codec, video_bitrate: v.video_bitrate,
      framerate: v.framerate, gop: v.gop, reference_frames: v.reference_frames,
      profile: v.profile, level: v.level,
      audio_codec: v.audio_codec, audio_bitrate: v.audio_bitrate, sample_rate: v.sample_rate,
      av1_preset: v.av1_preset, av1_segment_ext: v.av1_segment_ext,
    })),
  }
}

function RunningCell({ progressPct }) {
  const pct = typeof progressPct === 'number' ? progressPct : 0
  return (
    <Box sx={{ minWidth: 110 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <LinearProgress variant="determinate" value={pct} sx={{ flex: 1, height: 5, borderRadius: 2 }} />
        <Typography variant="caption" sx={{ fontWeight: 600, minWidth: 32, textAlign: 'right' }}>{pct}%</Typography>
      </Box>
      <Typography variant="caption" color="text.secondary">Encoding…</Typography>
    </Box>
  )
}

function CompletedCell({ completedAt, startedAt, status, progressPct }) {
  if (status === 'RUNNING') return <RunningCell progressPct={progressPct} />
  if (!completedAt) return <Typography variant="caption" color="text.secondary">—</Typography>
  const d = new Date(completedAt)
  return (
    <Box>
      <Typography variant="caption" display="block">
        {d.toLocaleDateString()} {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </Typography>
      {startedAt && (
        <Typography variant="caption" color="text.secondary">
          Transcode duration: {secsToHMS((d - new Date(startedAt)) / 1000)}
        </Typography>
      )}
    </Box>
  )
}

export default function JobsTable({ onClone }) {
  const [jobs, setJobs] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [logsJob, setLogsJob] = useState(null)
  const [detailJobId, setDetailJobId] = useState(null)
  const [error, setError] = useState('')
  const PER_PAGE = 15

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = { page, per_page: PER_PAGE }
      if (typeFilter) params.type = typeFilter
      if (statusFilter) params.status = statusFilter
      const data = await listJobs(params)
      setJobs(data.jobs || [])
      setTotal(data.total || 0)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [page, typeFilter, statusFilter])

  useEffect(() => { fetchJobs() }, [fetchJobs])
  useEffect(() => {
    const t = setInterval(fetchJobs, 3600000)
    return () => clearInterval(t)
  }, [fetchJobs])

  useEffect(() => {
    if (logsJob) {
      const updated = jobs.find(j => j.job_id === logsJob.job_id)
      if (updated && updated.status !== logsJob.status) {
        setLogsJob({ job_id: logsJob.job_id, status: updated.status })
      }
    }
  }, [jobs, logsJob])

  const handleStop = async (job) => {
    if (!window.confirm(`Stop ${job.type} job "${job.name}"?`)) return
    try {
      if (job.type === 'VOD') await stopVodJob(job.job_id)
      else await stopLiveChannel(job.job_id)
      fetchJobs()
    } catch (e) { alert(`Stop failed: ${e.message}`) }
  }

  const handleDelete = async (job) => {
    if (!window.confirm(`Delete job "${job.name}"? This cannot be undone.`)) return
    try {
      await deleteJob(job.job_id)
      fetchJobs()
    } catch (e) { alert(`Delete failed: ${e.message}`) }
  }

  const handleClone = async (job) => {
    try {
      const fullJob = await getJob(job.job_id)
      const prefillData = job.type === 'VOD' ? buildVodPrefill(fullJob) : buildLivePrefill(fullJob)
      onClone && onClone(job.type, prefillData)
    } catch (e) {
      alert(`Clone failed: ${e.message}`)
    }
  }

  const handleEdit = async (job) => {
    if (job.status === 'RUNNING') {
      if (!window.confirm(`Stop "${job.name}" and edit its configuration?`)) return
      try {
        await stopLiveChannel(job.job_id)
      } catch (e) {
        alert(`Stop failed: ${e.message}`)
        return
      }
    }
    try {
      const fullJob = await getJob(job.job_id)
      const prefillData = buildLivePrefill(fullJob)
      onClone && onClone('LIVE', prefillData)
    } catch (e) {
      alert(`Edit failed: ${e.message}`)
    }
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <Typography variant="h5" sx={{ flex: 1 }}>All Jobs</Typography>
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel>Type</InputLabel>
          <Select value={typeFilter} label="Type" onChange={(e) => { setTypeFilter(e.target.value); setPage(1) }}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="VOD">VOD</MenuItem>
            <MenuItem value="LIVE">Live</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Status</InputLabel>
          <Select value={statusFilter} label="Status" onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}>
            <MenuItem value="">All</MenuItem>
            {['RUNNING', 'COMPLETED', 'FAILED', 'STOPPED', 'PENDING'].map(s => (
              <MenuItem key={s} value={s}>{s}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <IconButton onClick={fetchJobs} disabled={loading}>
          <RefreshIcon sx={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
        </IconButton>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Card>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ '& th': { fontWeight: 600, bgcolor: 'rgba(124,110,250,0.12)' } }}>
                <TableCell>Channel Name</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Input</TableCell>
                <TableCell>Output</TableCell>
                <TableCell>Playback URL</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Completed / Progress</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {jobs.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 6, color: 'text.secondary' }}>No jobs found</TableCell>
                </TableRow>
              )}
              {jobs.map(job => (
                <TableRow key={job.job_id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{job.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{job.job_id.slice(0, 8)}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={job.type} size="small" variant="outlined" color={job.type === 'LIVE' ? 'error' : 'primary'} />
                  </TableCell>
                  <TableCell>
                    <Chip label={job.status} size="small" color={STATUS_COLORS[job.status] || 'default'} sx={{ fontWeight: 600 }} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 160 }}>
                    <Tooltip title={job.input_url}>
                      <Typography variant="caption" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                        {job.input_url}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{job.output_type} → {job.output_destination}</Typography>
                  </TableCell>
                  <TableCell sx={{ maxWidth: 180 }}>
                    {job.playback_url ? (
                      <Tooltip title={job.playback_url}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Typography variant="caption" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block', maxWidth: 140 }}>
                            {job.playback_url}
                          </Typography>
                          <IconButton size="small" onClick={() => navigator.clipboard.writeText(job.playback_url)}>
                            <ContentCopyIcon sx={{ fontSize: 12 }} />
                          </IconButton>
                        </Box>
                      </Tooltip>
                    ) : '—'}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</Typography>
                  </TableCell>
                  <TableCell sx={{ minWidth: 130 }}>
                    <CompletedCell completedAt={job.completed_at} startedAt={job.started_at} status={job.status} progressPct={job.progress_pct} />
                  </TableCell>
                  <TableCell align="right">
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
                      <Tooltip title="Details">
                        <IconButton size="small" onClick={() => setDetailJobId(job.job_id)}>
                          <InfoIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Logs">
                        <IconButton size="small" onClick={() => setLogsJob({ job_id: job.job_id, status: job.status })}>
                          <ListAltIconSmall />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Clone">
                        <IconButton size="small" color="primary" onClick={() => handleClone(job)}>
                          <FileCopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {job.type === 'LIVE' && (
                        <Tooltip title="Edit">
                          <IconButton size="small" color="secondary" onClick={() => handleEdit(job)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {job.status === 'RUNNING' && (
                        <Tooltip title="Stop">
                          <IconButton size="small" color="warning" onClick={() => handleStop(job)}>
                            <StopIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {job.status !== 'RUNNING' && (
                        <Tooltip title="Delete">
                          <IconButton size="small" color="error" onClick={() => handleDelete(job)}>
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>

      {total > PER_PAGE && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
          <Pagination count={Math.ceil(total / PER_PAGE)} page={page} onChange={(_, v) => setPage(v)} color="primary" />
        </Box>
      )}

      <LogsDialog open={!!logsJob} jobId={logsJob?.job_id} jobStatus={logsJob?.status} onClose={() => setLogsJob(null)} />
      <JobDetailDialog open={!!detailJobId} jobId={detailJobId} onClose={() => setDetailJobId(null)} />

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </Box>
  )
}

function ListAltIconSmall() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z"/>
    </svg>
  )
}

import React, { useState, useEffect, useCallback } from 'react'
import {
  Box, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, IconButton,
  Button, TextField, Select, MenuItem, FormControl, InputLabel,
  Dialog, DialogTitle, DialogContent, DialogActions, Tooltip,
  Alert, CircularProgress, Pagination, Stack,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import DeleteIcon from '@mui/icons-material/Delete'
import InfoIcon from '@mui/icons-material/Info'
import StopIcon from '@mui/icons-material/Stop'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { listJobs, getJob, getJobLogs, deleteJob, stopVodJob, stopLiveChannel } from '../../api/transcoder'

const STATUS_COLORS = {
  RUNNING: 'success',
  COMPLETED: 'info',
  FAILED: 'error',
  STOPPED: 'warning',
  PENDING: 'default',
}

function LogsDialog({ open, jobId, onClose }) {
  const [logs, setLogs] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !jobId) return
    setLoading(true)
    getJobLogs(jobId, 200)
      .then((d) => setLogs(d.logs || ''))
      .catch(() => setLogs('Failed to load logs'))
      .finally(() => setLoading(false))
  }, [open, jobId])

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Job Logs — {jobId?.slice(0, 8)}</DialogTitle>
      <DialogContent>
        {loading ? (
          <CircularProgress size={24} />
        ) : (
          <Box
            component="pre"
            sx={{ fontSize: 12, bgcolor: '#0d1117', p: 2, borderRadius: 1, overflow: 'auto', maxHeight: 500, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
          >
            {logs || 'No logs available'}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

function JobDetailDialog({ open, jobId, onClose }) {
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !jobId) return
    setLoading(true)
    getJob(jobId)
      .then(setJob)
      .catch(() => setJob(null))
      .finally(() => setLoading(false))
  }, [open, jobId])

  const copyUrl = () => {
    if (job?.playback_url) navigator.clipboard.writeText(job.playback_url)
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Job Details — {job?.name || jobId?.slice(0, 8)}</DialogTitle>
      <DialogContent>
        {loading ? (
          <CircularProgress size={24} />
        ) : job ? (
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
              <Detail label="Job ID" value={job.job_id} />
              <Detail label="Type" value={job.type} />
              <Detail label="Status" value={<Chip label={job.status} color={STATUS_COLORS[job.status] || 'default'} size="small" />} />
              <Detail label="Input" value={job.input_url} truncate />
              <Detail label="Output Type" value={job.output_type} />
              <Detail label="Destination" value={job.output_destination} />
              <Detail label="Preset" value={job.preset} />
              <Detail label="Segment (s)" value={job.segment_length} />
              <Detail label="Started" value={job.started_at} />
              <Detail label="Completed" value={job.completed_at} />
            </Box>
            {job.playback_url && (
              <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1 }}>
                <Typography variant="caption" color="text.secondary">Playback URL</Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                  <Typography variant="body2" sx={{ flex: 1, wordBreak: 'break-all', fontSize: 12 }}>
                    {job.playback_url}
                  </Typography>
                  <IconButton size="small" onClick={copyUrl}><ContentCopyIcon fontSize="small" /></IconButton>
                </Box>
              </Box>
            )}
            {job.error_message && (
              <Alert severity="error" sx={{ fontSize: 12 }}>
                <Box component="pre" sx={{ whiteSpace: 'pre-wrap', m: 0 }}>{job.error_message.slice(-500)}</Box>
              </Alert>
            )}
            {job.variants?.length > 0 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>Output Variants</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        {['Resolution', 'Video Codec', 'Video Bitrate', 'Audio Codec', 'Audio Bitrate', 'FPS'].map((h) => (
                          <TableCell key={h} sx={{ fontWeight: 600, fontSize: 11 }}>{h}</TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {job.variants.map((v, i) => (
                        <TableRow key={i}>
                          <TableCell>{v.width}×{v.height}</TableCell>
                          <TableCell>{v.video_codec}</TableCell>
                          <TableCell>{(v.video_bitrate / 1000).toFixed(0)}kbps</TableCell>
                          <TableCell>{v.audio_codec}</TableCell>
                          <TableCell>{(v.audio_bitrate / 1000).toFixed(0)}kbps</TableCell>
                          <TableCell>{v.framerate}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            )}
          </Stack>
        ) : (
          <Typography color="error">Failed to load job details</Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

function Detail({ label, value, truncate }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={truncate ? { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } : {}}>
        {value ?? '—'}
      </Typography>
    </Box>
  )
}

export default function JobsTable() {
  const [jobs, setJobs] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [logsJobId, setLogsJobId] = useState(null)
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

  // Auto-refresh every 5s
  useEffect(() => {
    const t = setInterval(fetchJobs, 5000)
    return () => clearInterval(t)
  }, [fetchJobs])

  const handleStop = async (job) => {
    if (!window.confirm(`Stop ${job.type} job "${job.name}"?`)) return
    try {
      if (job.type === 'VOD') await stopVodJob(job.job_id)
      else await stopLiveChannel(job.job_id)
      fetchJobs()
    } catch (e) {
      alert(`Stop failed: ${e.message}`)
    }
  }

  const handleDelete = async (job) => {
    if (!window.confirm(`Delete job "${job.name}"? This cannot be undone.`)) return
    try {
      await deleteJob(job.job_id)
      fetchJobs()
    } catch (e) {
      alert(`Delete failed: ${e.message}`)
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
            {['RUNNING', 'COMPLETED', 'FAILED', 'STOPPED', 'PENDING'].map((s) => (
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
                <TableCell>Name</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Input</TableCell>
                <TableCell>Output</TableCell>
                <TableCell>Playback URL</TableCell>
                <TableCell>Created</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {jobs.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 6, color: 'text.secondary' }}>
                    No jobs found
                  </TableCell>
                </TableRow>
              )}
              {jobs.map((job) => (
                <TableRow key={job.job_id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{job.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{job.job_id.slice(0, 8)}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={job.type} size="small" variant="outlined"
                      color={job.type === 'LIVE' ? 'error' : 'primary'} />
                  </TableCell>
                  <TableCell>
                    <Chip label={job.status} size="small" color={STATUS_COLORS[job.status] || 'default'}
                      sx={{ fontWeight: 600 }} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 180 }}>
                    <Tooltip title={job.input_url}>
                      <Typography variant="caption" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                        {job.input_url}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{job.output_type} → {job.output_destination}</Typography>
                  </TableCell>
                  <TableCell sx={{ maxWidth: 200 }}>
                    {job.playback_url ? (
                      <Tooltip title={job.playback_url}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Typography variant="caption" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block', maxWidth: 160 }}>
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
                    <Typography variant="caption">
                      {job.created_at ? new Date(job.created_at).toLocaleString() : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
                      <Tooltip title="Details">
                        <IconButton size="small" onClick={() => setDetailJobId(job.job_id)}>
                          <InfoIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Logs">
                        <IconButton size="small" onClick={() => setLogsJobId(job.job_id)}>
                          <ListAltIconSmall />
                        </IconButton>
                      </Tooltip>
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

      <LogsDialog open={!!logsJobId} jobId={logsJobId} onClose={() => setLogsJobId(null)} />
      <JobDetailDialog open={!!detailJobId} jobId={detailJobId} onClose={() => setDetailJobId(null)} />
    </Box>
  )
}

// Tiny inline icon to avoid import cycle
function ListAltIconSmall() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z"/>
    </svg>
  )
}

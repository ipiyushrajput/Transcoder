import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box, Card, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, IconButton,
  Button, TextField, Select, MenuItem, FormControl, InputLabel,
  Dialog, DialogTitle, DialogContent, DialogActions, Tooltip,
  Alert, CircularProgress, Pagination, Stack, LinearProgress,
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

    // Auto-refresh every 10s for RUNNING jobs; stop once done
    if (jobStatus === 'RUNNING') {
      intervalRef.current = setInterval(fetchLogs, 10000)
    }
    return () => clearInterval(intervalRef.current)
  }, [open, jobId, jobStatus, fetchLogs])

  // Stop polling when status changes away from RUNNING
  useEffect(() => {
    if (jobStatus !== 'RUNNING') clearInterval(intervalRef.current)
  }, [jobStatus])

  // Scroll to bottom when new logs arrive
  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        FFmpeg Logs — {jobId?.slice(0, 8)}
        <Chip
          label={jobStatus}
          color={STATUS_COLORS[jobStatus] || 'default'}
          size="small"
          sx={{ ml: 1 }}
        />
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={fetchLogs}><RefreshIcon fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
        ) : (
          <Box
            component="pre"
            sx={{
              fontSize: 11, bgcolor: '#0d1117', color: '#e6edf3', p: 2,
              borderRadius: 1, overflow: 'auto', maxHeight: 500,
              whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace',
            }}
          >
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

function JobDetailDialog({ open, jobId, onClose }) {
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !jobId) return
    setLoading(true)
    getJob(jobId).then(setJob).catch(() => setJob(null)).finally(() => setLoading(false))
  }, [open, jobId])

  const copyUrl = () => { if (job?.playback_url) navigator.clipboard.writeText(job.playback_url) }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Job Details — {job?.name || jobId?.slice(0, 8)}</DialogTitle>
      <DialogContent>
        {loading ? <CircularProgress size={24} /> : job ? (
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
              <Detail label="Channel Name" value={job.name} />
              <Detail label="Job ID" value={job.job_id} />
              <Detail label="Type" value={job.type} />
              <Detail label="Status" value={<Chip label={job.status} color={STATUS_COLORS[job.status] || 'default'} size="small" />} />
              <Detail label="Input" value={job.input_url} truncate />
              <Detail label="Output Type" value={job.output_type} />
              <Detail label="Destination" value={job.output_destination} />
              <Detail label="Preset" value={job.preset} />
              <Detail label="Segment (s)" value={job.segment_length} />
              <Detail label="Started" value={job.started_at} />
              <Detail label="Completed" value={job.completed_at || '—'} />
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
                <Typography variant="caption" fontWeight={700}>Error Details:</Typography>
                <Box component="pre" sx={{ whiteSpace: 'pre-wrap', m: 0, mt: 0.5, fontSize: 11 }}>
                  {job.error_message.slice(-1000)}
                </Box>
              </Alert>
            )}
            {job.variants?.length > 0 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>Output Variants</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        {['Resolution', 'Video Codec', 'Video Bitrate', 'Audio Codec', 'Audio Bitrate', 'FPS'].map(h => (
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
        ) : <Typography color="error">Failed to load job details</Typography>}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
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

function RunningCell({ progressPct }) {
  const pct = typeof progressPct === 'number' ? progressPct : 0
  return (
    <Box sx={{ minWidth: 110 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <LinearProgress
          variant="determinate"
          value={pct}
          sx={{ flex: 1, height: 5, borderRadius: 2 }}
        />
        <Typography variant="caption" sx={{ fontWeight: 600, minWidth: 32, textAlign: 'right' }}>
          {pct}%
        </Typography>
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
          {Math.round((d - new Date(startedAt)) / 1000)}s duration
        </Typography>
      )}
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
  const [logsJob, setLogsJob] = useState(null)   // { job_id, status }
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

  // Keep logs dialog job status in sync with jobs list
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
                  <TableCell colSpan={9} align="center" sx={{ py: 6, color: 'text.secondary' }}>
                    No jobs found
                  </TableCell>
                </TableRow>
              )}
              {jobs.map(job => (
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
                    <Typography variant="caption">
                      {job.created_at ? new Date(job.created_at).toLocaleString() : '—'}
                    </Typography>
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

      <LogsDialog
        open={!!logsJob}
        jobId={logsJob?.job_id}
        jobStatus={logsJob?.status}
        onClose={() => setLogsJob(null)}
      />
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

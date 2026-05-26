import React, { useState } from 'react'
import {
  Box, Button, Alert, CircularProgress, Snackbar, Typography,
  Chip, Dialog, DialogTitle, DialogContent, DialogActions, Stack,
  TextField, IconButton,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StopIcon from '@mui/icons-material/Stop'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import InputSection from './InputSection'
import OutputSection from './OutputSection'
import VideoAudioConfig from './VideoAudioConfig'
import AdSignaling from './AdSignaling'
import { startVodJob, stopVodJob } from '../../api/transcoder'

const DEFAULT_INPUT = {
  channel_name: '',
  input_type: 'FILE',
  input_url: '',
  clips: [],
  subtitle_url: '',
  subtitle_language: 'en',
}

const DEFAULT_OUTPUT = {
  output_type: 'HLS',
  output_destination: 'LOCAL',
  s3_bucket: '',
  s3_path: '',
  s3_cloudfront_domain: '',
  local_path: '',
  master_filename: 'master',
  segment_length: 6,
  hls_playlist_type: 'vod',
  hls_flags: 'independent_segments',
  hls_list_size: 0,
  preset: 'medium',
}

const DEFAULT_ESAM = {
  esam_enabled: false,
  esam_scc_xml: '',
  esam_mcc_xml: '',
}

function JobStartedDialog({ open, jobId, playbackUrl, onClose, onStop }) {
  const copy = (text) => navigator.clipboard.writeText(text)

  return (
    <Dialog open={open} maxWidth="sm" fullWidth onClose={onClose}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Chip label="RUNNING" color="success" size="small" />
        VOD Job Started
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Job ID</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>{jobId}</Typography>
              <IconButton size="small" onClick={() => copy(jobId)}><ContentCopyIcon fontSize="small" /></IconButton>
            </Box>
          </Box>
          {playbackUrl && (
            <Box>
              <Typography variant="caption" color="text.secondary">Playback URL</Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <TextField
                  fullWidth size="small" value={playbackUrl} InputProps={{ readOnly: true }}
                  sx={{ '& input': { fontSize: 12, fontFamily: 'monospace' } }}
                />
                <IconButton size="small" onClick={() => copy(playbackUrl)}><ContentCopyIcon fontSize="small" /></IconButton>
              </Box>
            </Box>
          )}
          <Alert severity="info">
            Transcoding is running in the background. Check the Jobs tab for status and logs.
          </Alert>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button color="warning" startIcon={<StopIcon />} onClick={() => onStop(jobId)}>Stop Job</Button>
        <Button variant="contained" onClick={onClose}>Close &amp; View Jobs</Button>
      </DialogActions>
    </Dialog>
  )
}

export default function VODTranscoder({ onNavigateToJobs }) {
  const [input, setInput] = useState(DEFAULT_INPUT)
  const [output, setOutput] = useState(DEFAULT_OUTPUT)
  const [variants, setVariants] = useState([])
  const [esam, setEsam] = useState(DEFAULT_ESAM)

  const [submitting, setSubmitting] = useState(false)
  const [jobStarted, setJobStarted] = useState(null)
  const [snack, setSnack] = useState({ open: false, msg: '', severity: 'info' })
  const [errors, setErrors] = useState({})

  const showSnack = (msg, severity = 'info') => setSnack({ open: true, msg, severity })

  const validate = () => {
    const e = {}
    if (!input.channel_name?.trim()) e.channel_name = 'Channel Name is required'
    if (!input.input_url?.trim()) e.input_url = 'Input URL is required'
    if (variants.length === 0) e.variants = 'At least one output variant is required'
    if (output.output_destination === 'S3' && !output.s3_bucket?.trim()) e.s3_bucket = 'S3 bucket is required'
    if (output.output_destination === 'LOCAL' && !output.local_path?.trim()) e.local_path = 'Local output path is required'
    if (esam.esam_enabled && !esam.esam_scc_xml?.trim()) e.esam = 'SCC XML is required when ESAM is enabled'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleStart = async () => {
    if (!validate()) {
      showSnack('Please fix validation errors before submitting', 'error')
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        name: input.channel_name?.trim() || output.master_filename || 'vod-job',
        ...input,
        ...output,
        variants: variants,
        ...esam,
      }
      const result = await startVodJob(payload)
      setJobStarted({ jobId: result.job_id, playbackUrl: result.playback_url })
      showSnack('VOD job started successfully', 'success')
    } catch (e) {
      showSnack(`Failed to start: ${e.message}`, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleStop = async (jobId) => {
    try {
      await stopVodJob(jobId)
      setJobStarted(null)
      showSnack('Job stopped', 'warning')
    } catch (e) {
      showSnack(`Stop failed: ${e.message}`, 'error')
    }
  }

  const handleReset = () => {
    setInput(DEFAULT_INPUT)
    setOutput(DEFAULT_OUTPUT)
    setVariants([])
    setEsam(DEFAULT_ESAM)
    setErrors({})
    setJobStarted(null)
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <Typography variant="h5" sx={{ flex: 1 }}>
          VOD Transcoding Job
        </Typography>
        <Chip label="AWS MediaConvert-style" variant="outlined" size="small" color="primary" />
      </Box>

      <Stack spacing={2.5}>
        {/* Validation Summary */}
        {Object.keys(errors).length > 0 && (
          <Alert severity="error">
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>Please fix the following:</Typography>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {Object.values(errors).map((e, i) => <li key={i}><Typography variant="caption">{e}</Typography></li>)}
            </ul>
          </Alert>
        )}

        <InputSection value={input} onChange={setInput} />
        <OutputSection value={output} onChange={setOutput} />
        <VideoAudioConfig value={variants} onChange={setVariants} />
        <AdSignaling value={esam} onChange={setEsam} />

        {/* Submit Controls */}
        <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', pb: 4 }}>
          <Button variant="outlined" startIcon={<RestartAltIcon />} onClick={handleReset} disabled={submitting}>
            Reset
          </Button>
          <Button
            variant="contained" size="large" startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : <PlayArrowIcon />}
            onClick={handleStart}
            disabled={submitting}
            sx={{ minWidth: 180, bgcolor: 'primary.main' }}
          >
            {submitting ? 'Starting...' : 'Start Transcoding'}
          </Button>
        </Box>
      </Stack>

      {jobStarted && (
        <JobStartedDialog
          open={!!jobStarted}
          jobId={jobStarted.jobId}
          playbackUrl={jobStarted.playbackUrl}
          onClose={() => { setJobStarted(null); onNavigateToJobs && onNavigateToJobs() }}
          onStop={handleStop}
        />
      )}

      <Snackbar
        open={snack.open}
        autoHideDuration={5000}
        onClose={() => setSnack({ ...snack, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snack.severity} onClose={() => setSnack({ ...snack, open: false })}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  )
}

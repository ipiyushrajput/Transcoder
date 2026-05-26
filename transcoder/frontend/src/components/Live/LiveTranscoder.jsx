import React, { useState } from 'react'
import {
  Box, Button, Alert, CircularProgress, Snackbar, Typography,
  Chip, Dialog, DialogTitle, DialogContent, DialogActions, Stack,
  TextField, IconButton,
} from '@mui/material'
import LiveTvIcon from '@mui/icons-material/LiveTv'
import StopIcon from '@mui/icons-material/Stop'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord'
import LiveInputSection from './InputSection'
import LiveOutputSection from './OutputSection'
import LiveVideoAudioConfig from './VideoAudioConfig'
import { startLiveChannel, stopLiveChannel } from '../../api/transcoder'

const DEFAULT_INPUT = { channel_name: '', input_type: 'RTMP', input_url: '' }
const DEFAULT_OUTPUT = {
  output_type: 'HLS', output_destination: 'LOCAL',
  s3_bucket: '', s3_path: '', s3_cloudfront_domain: '',
  local_path: '', mediapackage_url: '', mediapackage_user: '', mediapackage_password: '',
  rtmp_output_url: '', master_filename: 'live', segment_length: 4,
  hls_list_size: 6, hls_flags: 'delete_segments+append_list', preset: 'veryfast',
}

function ChannelRunningDialog({ open, channelId, playbackUrl, onClose, onStop }) {
  const copy = (text) => navigator.clipboard.writeText(text)

  return (
    <Dialog open={open} maxWidth="sm" fullWidth onClose={onClose}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <FiberManualRecordIcon color="error" sx={{ animation: 'pulse 1.5s infinite' }} />
        <Chip label="LIVE" color="error" size="small" sx={{ fontWeight: 700 }} />
        Channel Running
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Channel ID</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>{channelId}</Typography>
              <IconButton size="small" onClick={() => copy(channelId)}><ContentCopyIcon fontSize="small" /></IconButton>
            </Box>
          </Box>
          {playbackUrl && (
            <Box>
              <Typography variant="caption" color="text.secondary">Playback URL</Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <TextField fullWidth size="small" value={playbackUrl} InputProps={{ readOnly: true }} sx={{ '& input': { fontSize: 12, fontFamily: 'monospace' } }} />
                <IconButton size="small" onClick={() => copy(playbackUrl)}><ContentCopyIcon fontSize="small" /></IconButton>
              </Box>
            </Box>
          )}
          <Alert severity="warning">
            Live channel is running. Stopping it will terminate the stream immediately.
          </Alert>
          <Alert severity="info">
            Monitor your channel in the Jobs tab. Segments are being generated continuously.
          </Alert>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button color="error" variant="contained" startIcon={<StopIcon />} onClick={() => onStop(channelId)}>
          Stop Channel
        </Button>
        <Button variant="outlined" onClick={onClose}>Close &amp; View Jobs</Button>
      </DialogActions>
    </Dialog>
  )
}

export default function LiveTranscoder({ onNavigateToJobs }) {
  const [input, setInput] = useState(DEFAULT_INPUT)
  const [output, setOutput] = useState(DEFAULT_OUTPUT)
  const [variants, setVariants] = useState([])
  const [channelRunning, setChannelRunning] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState({})
  const [snack, setSnack] = useState({ open: false, msg: '', severity: 'info' })

  const showSnack = (msg, severity = 'info') => setSnack({ open: true, msg, severity })

  const validate = () => {
    const e = {}
    if (!input.channel_name?.trim()) e.channel_name = 'Channel Name is required'
    if (!input.input_url?.trim()) e.input_url = 'Live input URL is required'
    if (variants.length === 0) e.variants = 'At least one output variant is required'
    if (output.output_type === 'HLS') {
      if (output.output_destination === 'S3' && !output.s3_bucket?.trim()) e.s3_bucket = 'S3 bucket is required'
      if (output.output_destination === 'LOCAL' && !output.local_path?.trim()) e.local_path = 'Local path is required'
      if (output.output_destination === 'MEDIAPACKAGE' && !output.mediapackage_url?.trim()) e.mediapackage_url = 'MediaPackage URL is required'
    }
    if (output.output_type === 'RTMP' && !output.rtmp_output_url?.trim()) e.rtmp = 'RTMP output URL is required'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleStart = async () => {
    if (!validate()) {
      showSnack('Please fix validation errors', 'error')
      return
    }
    setSubmitting(true)
    try {
      const payload = {
        name: input.channel_name?.trim() || output.master_filename || 'live-channel',
        ...input,
        ...output,
        variants,
      }
      const result = await startLiveChannel(payload)
      setChannelRunning({ channelId: result.channel_id, playbackUrl: result.playback_url })
      showSnack('Live channel started!', 'success')
    } catch (e) {
      showSnack(`Failed to start: ${e.message}`, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleStop = async (channelId) => {
    try {
      await stopLiveChannel(channelId)
      setChannelRunning(null)
      showSnack('Channel stopped', 'warning')
    } catch (e) {
      showSnack(`Stop failed: ${e.message}`, 'error')
    }
  }

  const handleReset = () => {
    setInput(DEFAULT_INPUT)
    setOutput(DEFAULT_OUTPUT)
    setVariants([])
    setErrors({})
    setChannelRunning(null)
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <LiveTvIcon color="error" />
        <Typography variant="h5" sx={{ flex: 1 }}>Live Transcoding Channel</Typography>
        <Chip label="AWS MediaLive-style" variant="outlined" size="small" color="error" />
        {channelRunning && (
          <Chip
            label="LIVE"
            color="error"
            icon={<FiberManualRecordIcon sx={{ animation: 'pulse 1.5s infinite' }} />}
            sx={{ fontWeight: 700 }}
          />
        )}
      </Box>

      <Stack spacing={2.5}>
        {Object.keys(errors).length > 0 && (
          <Alert severity="error">
            <Typography variant="body2" fontWeight={600} mb={0.5}>Please fix:</Typography>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {Object.values(errors).map((e, i) => <li key={i}><Typography variant="caption">{e}</Typography></li>)}
            </ul>
          </Alert>
        )}

        <LiveInputSection value={input} onChange={setInput} />
        <LiveOutputSection value={output} onChange={setOutput} />
        <LiveVideoAudioConfig value={variants} onChange={setVariants} />

        <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', pb: 4 }}>
          <Button variant="outlined" startIcon={<RestartAltIcon />} onClick={handleReset} disabled={submitting || !!channelRunning}>Reset</Button>
          {channelRunning ? (
            <Button
              variant="contained" color="error" size="large"
              startIcon={<StopIcon />}
              onClick={() => handleStop(channelRunning.channelId)}
              sx={{ minWidth: 180 }}
            >
              Stop Channel
            </Button>
          ) : (
            <Button
              variant="contained" size="large" color="error"
              startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : <LiveTvIcon />}
              onClick={handleStart}
              disabled={submitting}
              sx={{ minWidth: 200 }}
            >
              {submitting ? 'Starting...' : 'Start Live Channel'}
            </Button>
          )}
        </Box>
      </Stack>

      {channelRunning && (
        <ChannelRunningDialog
          open={!!channelRunning}
          channelId={channelRunning.channelId}
          playbackUrl={channelRunning.playbackUrl}
          onClose={() => { setChannelRunning(null); onNavigateToJobs && onNavigateToJobs() }}
          onStop={handleStop}
        />
      )}

      <Snackbar open={snack.open} autoHideDuration={5000} onClose={() => setSnack({ ...snack, open: false })} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
        <Alert severity={snack.severity} onClose={() => setSnack({ ...snack, open: false })}>{snack.msg}</Alert>
      </Snackbar>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </Box>
  )
}

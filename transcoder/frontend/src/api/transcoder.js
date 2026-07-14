import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5001'

const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message = err.response?.data?.error || err.message || 'Request failed'
    return Promise.reject(new Error(message))
  }
)

// --- Common ---
export const getTemplates = () => api.get('/api/templates').then((r) => r.data)
export const getAv1Encoders = () => api.get('/api/av1-encoders').then((r) => r.data)
export const probeInput = (url) => api.post('/api/probe', { url }).then((r) => r.data)
export const getSystemStatus = () => api.get('/api/status').then((r) => r.data)
export const listJobs = (params = {}) => api.get('/api/jobs', { params }).then((r) => r.data)
export const getJob = (jobId) => api.get(`/api/jobs/${jobId}`).then((r) => r.data)
export const getJobLogs = (jobId, tail = 100) => api.get(`/api/jobs/${jobId}/logs`, { params: { tail } }).then((r) => r.data)
export const deleteJob = (jobId) => api.delete(`/api/jobs/${jobId}`).then((r) => r.data)

// --- VOD ---
export const validateVodInput = (url) => api.post('/api/vod/validate-input', { url }).then((r) => r.data)
export const startVodJob = (payload) => api.post('/api/vod/start', payload).then((r) => r.data)
export const stopVodJob = (jobId) => api.post('/api/vod/stop', { job_id: jobId }).then((r) => r.data)
export const getVodJobStatus = (jobId) => api.get(`/api/vod/status/${jobId}`).then((r) => r.data)

// --- Live ---
export const validateLiveInput = (url) => api.post('/api/live/validate-input', { url }).then((r) => r.data)
export const startLiveChannel = (payload) => api.post('/api/live/start', payload).then((r) => r.data)
export const stopLiveChannel = (channelId) => api.post('/api/live/stop', { channel_id: channelId }).then((r) => r.data)
export const getLiveChannelStatus = (channelId) => api.get(`/api/live/status/${channelId}`).then((r) => r.data)

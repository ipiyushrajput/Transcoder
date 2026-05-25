import React, { useState } from 'react'
import {
  Box, AppBar, Toolbar, Typography, Tabs, Tab, Container, Chip,
} from '@mui/material'
import MovieIcon from '@mui/icons-material/Movie'
import LiveTvIcon from '@mui/icons-material/LiveTv'
import ListAltIcon from '@mui/icons-material/ListAlt'
import VODTranscoder from './VOD/VODTranscoder'
import LiveTranscoder from './Live/LiveTranscoder'
import JobsTable from './shared/JobsTable'

export default function TranscoderPage() {
  const [tab, setTab] = useState(0)

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static" elevation={0} sx={{ bgcolor: 'background.paper', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
        <Toolbar>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mr: 4 }}>
            <Box
              component="img"
              src="https://images.samsung.com/is/image/samsung/assets/in/tvs/smart-tv/samsung-tv-plus/samsung-tv-plus-icon.jpg"
              alt="Samsung TV Plus"
              sx={{ width: 36, height: 36, borderRadius: 2, objectFit: 'cover', flexShrink: 0 }}
            />
            <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: '-0.5px' }}>
              Transcoder
            </Typography>
            <Chip label="Production" size="small" color="secondary" sx={{ height: 20, fontSize: 10 }} />
          </Box>
          <Tabs
            value={tab}
            onChange={(_, v) => setTab(v)}
            sx={{
              '& .MuiTab-root': { minWidth: 120, fontWeight: 600, fontSize: 14 },
              '& .MuiTabs-indicator': { bgcolor: 'primary.main', height: 3, borderRadius: '3px 3px 0 0' },
            }}
          >
            <Tab icon={<MovieIcon fontSize="small" />} iconPosition="start" label="VOD" />
            <Tab icon={<LiveTvIcon fontSize="small" />} iconPosition="start" label="Live" />
            <Tab icon={<ListAltIcon fontSize="small" />} iconPosition="start" label="Jobs" />
          </Tabs>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        {tab === 0 && <VODTranscoder />}
        {tab === 1 && <LiveTranscoder />}
        {tab === 2 && <JobsTable />}
      </Container>
    </Box>
  )
}

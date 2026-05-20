import React from 'react'
import { ThemeProvider, CssBaseline } from '@mui/material'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import theme from './theme/theme'
import TranscoderPage from './components/TranscoderPage'

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/transcoder" replace />} />
          <Route path="/transcoder/*" element={<TranscoderPage />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}

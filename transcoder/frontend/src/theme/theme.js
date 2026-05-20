import { createTheme } from '@mui/material/styles'

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#7C6EFA',
      light: '#A89CF9',
      dark: '#5848C8',
    },
    secondary: {
      main: '#00C896',
      light: '#4FEBB8',
      dark: '#009E77',
    },
    background: {
      default: '#0F1117',
      paper: '#1A1D27',
    },
    error: { main: '#F44336' },
    warning: { main: '#FF9800' },
    success: { main: '#4CAF50' },
    info: { main: '#29B6F6' },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", sans-serif',
    h4: { fontWeight: 700 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: { borderRadius: 12, border: '1px solid rgba(255,255,255,0.08)' },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 8, textTransform: 'none', fontWeight: 600 },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: { '& .MuiOutlinedInput-root': { borderRadius: 8 } },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 6 },
      },
    },
  },
})

export default theme

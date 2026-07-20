import { createTheme, alpha } from '@mui/material/styles';

export const getAppTheme = (mode: 'light' | 'dark') => {
  const isDark = mode === 'dark';
  const glassBg = isDark ? alpha('#16181d', 0.7) : alpha('#ffffff', 0.85);
  const glassBorder = `1px solid ${isDark ? alpha('#ffffff', 0.05) : alpha('#6347f6', 0.15)}`;

  return createTheme({
    palette: {
      mode,
      primary: {
        main: '#8b5cf6', // Gold/orange
      },
      secondary: {
        main: '#22c55e', // Profit green
      },
      error: {
        main: '#ef4444', // Loss red
      },
      warning: {
        main: '#3b82f6', // Replaces yellow/orange
      },
      background: {
        default: isDark ? '#0a0b0f' : '#fafafe',
        paper: isDark ? '#16181d' : '#ffffff',
      },
      text: {
        primary: isDark ? '#ffffff' : '#0f0f1a',
        secondary: isDark ? '#a0a5b1' : '#55597d',
      },
    },
    typography: {
      fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
      h1: { fontWeight: 700 },
      h2: { fontWeight: 700 },
      h3: { fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: '0.875rem' },
      h4: { fontWeight: 600 },
      h5: { fontWeight: 600 },
      h6: { fontWeight: 600 },
      button: { textTransform: 'none', fontWeight: 500 },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            backgroundColor: isDark ? '#0a0b0f' : '#fafafe',
            backgroundImage: isDark 
              ? 'radial-gradient(circle at 50% 0%, #1a1e28 0%, #0a0b0f 70%)' 
              : 'radial-gradient(circle at 50% 0%, #e0e4f7 0%, #fafafe 70%)',
            backgroundAttachment: 'fixed',
            minHeight: '100vh',
            color: isDark ? '#ffffff' : '#0f0f1a',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundColor: glassBg,
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            border: glassBorder,
            borderRadius: 16,
            boxShadow: isDark 
              ? '0 8px 32px 0 rgba(0, 0, 0, 0.3)' 
              : '0 8px 32px 0 rgba(99, 71, 246, 0.05)',
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            padding: '8px 16px',
          },
        },
        variants: [
          {
            props: { variant: 'contained', color: 'primary' },
            style: {
              background: 'linear-gradient(45deg, #8b5cf6 30%, #3b82f6 90%)',
              color: '#0a0b0f',
              fontWeight: 600,
              '&:hover': {
                background: 'linear-gradient(45deg, #3b82f6 30%, #8b5cf6 90%)',
              },
            },
          },
        ],
      },
      MuiCard: {
        styleOverrides: {
          root: {
            backgroundColor: glassBg,
            backdropFilter: 'blur(12px)',
            border: glassBorder,
            borderRadius: 16,
          },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: {
            borderBottom: `1px solid ${isDark ? alpha('#ffffff', 0.05) : alpha('#6347f6', 0.08)}`,
            color: isDark ? '#ffffff' : '#0f0f1a',
          },
          head: {
            color: isDark ? '#a0a5b1' : '#55597d',
            textTransform: 'uppercase',
            fontSize: '0.75rem',
            fontWeight: 600,
            letterSpacing: '0.05em',
            borderBottom: `2px solid ${isDark ? alpha('#ffffff', 0.1) : alpha('#6347f6', 0.15)}`,
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            backgroundColor: isDark ? alpha('#000000', 0.2) : alpha('#ffffff', 0.8),
            borderRadius: 8,
            '& fieldset': {
              borderColor: isDark ? alpha('#ffffff', 0.1) : alpha('#6347f6', 0.2),
            },
            '&:hover fieldset': {
              borderColor: isDark ? alpha('#ffffff', 0.2) : alpha('#6347f6', 0.35),
            },
            '&.Mui-focused fieldset': {
              borderColor: '#8b5cf6',
            },
            '& .MuiOutlinedInput-input': {
              color: isDark ? '#ffffff' : '#0f0f1a',
            }
          },
        },
      },
    },
  });
};

export const theme = getAppTheme('dark');

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Typography, Card, CardContent, TextField, Button, Grid, CircularProgress, IconButton, Paper, Chip } from '@mui/material';
import { BookOpen, Trash2, AlertCircle, History, Plus } from 'lucide-react';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

interface JournalEntry {
  id: number;
  ticker: string | null;
  title: string;
  body: string;
  mood: string;
  tags: string | null;
  trade_type: string;
  created_at: string;
}

interface PredictionLog {
  id: number;
  ticker: string;
  interval: string;
  current_price: number;
  lr_pred: number;
  rf_pred: number;
  direction: string;
  confidence: number;
  predicted_at: string;
}

const MOOD_ICONS: Record<string, string> = { 
  great: '😄', 
  good: '🙂', 
  neutral: '😐', 
  bad: '🙁', 
  terrible: '😤' 
};

export const JournalDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [history, setHistory] = useState<PredictionLog[]>([]);
  const [loading, setLoading] = useState(true);

  // Form State
  const [title, setTitle] = useState('');
  const [ticker, setTicker] = useState('');
  const [tradeType, setTradeType] = useState('long');
  const [mood, setMood] = useState('neutral');
  const [body, setBody] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // Filters State
  const [filterTicker, setFilterTicker] = useState('');
  const [filterTag, setFilterTag] = useState('');

  const fetchJournal = useCallback(async () => {
    try {
      const data = await apiFetch('/api/journal');
      if (data.ok) {
        setEntries(data.entries || []);
      }
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const data = await apiFetch('/api/predict/history');
      if (data.ok) {
        setHistory(data.history || []);
      }
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await Promise.all([fetchJournal(), fetchHistory()]);
      setLoading(false);
    };
    loadAll();
  }, [fetchJournal, fetchHistory]);

  const handleAddTag = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && tagsInput.trim()) {
      e.preventDefault();
      const newTag = tagsInput.trim().toLowerCase().replace(/[^a-zA-Z0-9\-_]/g, '');
      if (newTag && !tags.includes(newTag)) {
        setTags([...tags, newTag]);
      }
      setTagsInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((t) => t !== tagToRemove));
  };

  // Action: Autofill from previous prediction trade logs
  const handleAutofill = (pred: PredictionLog) => {
    const formattedDate = new Date(pred.predicted_at).toLocaleDateString();
    setTicker(pred.ticker);
    setTitle(`ML Trade Log: ${pred.ticker} (${pred.direction})`);
    setTradeType(pred.direction === 'Up' ? 'long' : pred.direction === 'Down' ? 'short' : 'paper');
    setMood(pred.direction === 'Up' ? 'great' : pred.direction === 'Down' ? 'bad' : 'neutral');
    setBody(
      `Automated prediction details:\n` +
      `- Ticker: ${pred.ticker}\n` +
      `- Prediction Date: ${formattedDate}\n` +
      `- Timeframe: ${pred.interval}\n` +
      `- Signal: ${pred.direction === 'Up' ? 'Bullish (Up)' : pred.direction === 'Down' ? 'Bearish (Down)' : 'Hold'}\n` +
      `- Entry Price: $${pred.current_price.toFixed(2)}\n` +
      `- Predicted Close: $${pred.lr_pred.toFixed(2)}\n` +
      `- Confidence: ${pred.confidence.toFixed(1)}%\n\n` +
      `[Explain your psychological state, entry/exit executions, and risk parameters here...]`
    );
    setTags([pred.ticker.toLowerCase(), 'ml_prediction', pred.interval]);
    toast.success(`Autofilled from ${pred.ticker} prediction history!`);
  };

  const handleSaveEntry = async () => {
    if (!title.trim()) {
      toast.error('Title is required');
      return;
    }
    if (!body.trim()) {
      toast.error('Notes are required');
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiFetch('/api/journal', {
        method: 'POST',
        body: {
          title,
          body,
          ticker: ticker.trim().toUpperCase() || null,
          mood,
          trade_type: tradeType,
          tags: tags.join(','),
        }
      });
      if (res.ok) {
        toast.success('Journal entry recorded!');
        // Reset form
        setTitle('');
        setTicker('');
        setBody('');
        setTags([]);
        setMood('neutral');
        setTradeType('long');
        fetchJournal();
      } else {
        toast.error(res.error || 'Failed to record journal entry');
      }
    } catch (err) {
      toast.error('Network error saving journal');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteEntry = async (id: number) => {
    if (!confirm('Are you sure you want to delete this journal entry?')) return;
    try {
      const res = await apiFetch('/api/journal', {
        method: 'DELETE',
        body: { id }
      });
      if (res.ok) {
        toast.success('Journal entry removed');
        fetchJournal();
      } else {
        toast.error(res.error || 'Failed to delete entry');
      }
    } catch (err) {
      toast.error('Failed to remove entry');
    }
  };

  // Filtered Entries
  const filteredEntries = entries.filter((e) => {
    const matchesTicker = !filterTicker || (e.ticker || '').toUpperCase().includes(filterTicker.toUpperCase());
    const matchesTag = !filterTag || (e.tags || '').toLowerCase().includes(filterTag.toLowerCase());
    return matchesTicker && matchesTag;
  });

  // Calculate statistics
  const totalEntries = entries.length;
  const tickersCount = new Set(entries.map((e) => e.ticker).filter(Boolean)).size;
  const allTags = entries.flatMap((e) => (e.tags || '').split(',').filter(Boolean));
  const uniqueTagsCount = new Set(allTags).size;

  const moodRatings: Record<string, number> = { great: 5, good: 4, neutral: 3, bad: 2, terrible: 1 };
  const moodsList = entries.map((e) => moodRatings[e.mood]).filter(Boolean);
  const avgMoodValue = moodsList.length ? moodsList.reduce((a, b) => a + b, 0) / moodsList.length : 3;
  const avgMoodIcon = avgMoodValue >= 4.5 ? '😄' : avgMoodValue >= 3.5 ? '🙂' : avgMoodValue >= 2.5 ? '😐' : avgMoodValue >= 1.5 ? '🙁' : '😤';

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.5, color: 'text.primary' }}>
            <BookOpen color="#3b82f6" />
            Trade Journal
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Document your trade setups, emotional states, and key market observations.
          </Typography>
        </Box>
      </Box>

      {/* Stats Cards */}
      {totalEntries > 0 && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 6, sm: 3 }}>
            <Card sx={{ textAlign: 'center' }}>
              <CardContent sx={{ p: 2 }}>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Total Entries</Typography>
                <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5 }}>{totalEntries}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <Card sx={{ textAlign: 'center' }}>
              <CardContent sx={{ p: 2 }}>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Average Mood</Typography>
                <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5 }}>{avgMoodIcon}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <Card sx={{ textAlign: 'center' }}>
              <CardContent sx={{ p: 2 }}>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Tickers Logged</Typography>
                <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5 }}>{tickersCount}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <Card sx={{ textAlign: 'center' }}>
              <CardContent sx={{ p: 2 }}>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Unique Tags</Typography>
                <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5 }}>{uniqueTagsCount}</Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {loading ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 10, gap: 2 }}>
          <CircularProgress size={30} />
          <Typography color="text.secondary" variant="body2">Loading journal details...</Typography>
        </Box>
      ) : (
        <Grid container spacing={3}>
          {/* Creation Form */}
          <Grid size={{ xs: 12, md: 5 }}>
            <Card sx={{ position: 'sticky', top: 20 }}>
              <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>New Entry</Typography>
              </Box>
              <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
                <TextField 
                  label="Title" 
                  size="small" 
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. AAPL breakout above $200"
                  fullWidth
                />
                
                <TextField 
                  label="Ticker (optional)" 
                  size="small" 
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  placeholder="AAPL"
                  fullWidth
                />

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 1 }}>Trade Type</Typography>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {['long', 'short', 'paper', 'insight'].map((type) => (
                      <Button 
                        key={type}
                        size="small"
                        variant={tradeType === type ? 'contained' : 'outlined'}
                        onClick={() => setTradeType(type)}
                        sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}
                      >
                        {type}
                      </Button>
                    ))}
                  </Box>
                </Box>

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 1 }}>Mood</Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    {Object.entries(MOOD_ICONS).map(([key, emoji]) => (
                      <Button 
                        key={key}
                        variant={mood === key ? 'contained' : 'outlined'}
                        onClick={() => setMood(key)}
                        sx={{ fontSize: '1.2rem', minWidth: 46, p: 0.5 }}
                        title={key}
                      >
                        {emoji}
                      </Button>
                    ))}
                  </Box>
                </Box>

                <TextField 
                  label="Notes" 
                  multiline 
                  rows={4} 
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="Describe your setup, reasoning, and lessons learned..."
                  fullWidth
                />

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 1 }}>Tags (Press Enter)</Typography>
                  <Paper sx={{ p: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5, border: '1px solid rgba(255,255,255,0.05)', bgcolor: 'rgba(0,0,0,0.15)' }}>
                    {tags.map((t) => (
                      <Chip 
                        key={t}
                        label={`#${t}`} 
                        size="small" 
                        onDelete={() => handleRemoveTag(t)}
                        sx={{ fontWeight: 'medium' }}
                      />
                    ))}
                    <input 
                      type="text" 
                      placeholder="Add tag..."
                      value={tagsInput}
                      onChange={(e) => setTagsInput(e.target.value)}
                      onKeyDown={handleAddTag}
                      style={{ 
                        background: 'transparent', 
                        border: 'none', 
                        outline: 'none', 
                        color: '#fff', 
                        fontSize: '0.875rem',
                        flex: 1,
                        minWidth: 80
                      }}
                    />
                  </Paper>
                </Box>

                <Button 
                  variant="contained" 
                  color="primary" 
                  fullWidth 
                  onClick={handleSaveEntry}
                  disabled={submitting}
                  sx={{ fontWeight: 'bold', mt: 1 }}
                >
                  {submitting ? 'Saving...' : 'Save Entry'}
                </Button>
              </CardContent>
            </Card>
          </Grid>

          {/* Entries list and previous trades autofill */}
          <Grid size={{ xs: 12, md: 7 }} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            
            {/* Previous Predictions / Trades List */}
            {history.length > 0 && (
              <Card sx={{ border: '1px solid rgba(59, 130, 246, 0.2)', bgcolor: 'rgba(59, 130, 246, 0.01)' }}>
                <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 1 }}>
                  <History size={16} color="#3b82f6" />
                  <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Quick-Log Previous Predictions</Typography>
                </Box>
                <CardContent sx={{ p: 2, display: 'flex', gap: 1.5, overflowX: 'auto', whiteSpace: 'nowrap' }}>
                  {history.slice(0, 8).map((pred) => (
                    <Box 
                      key={pred.id}
                      onClick={() => handleAutofill(pred)}
                      sx={{ 
                        display: 'inline-flex',
                        flexDirection: 'column',
                        gap: 0.5,
                        p: 1.5, 
                        border: '1px solid rgba(255,255,255,0.05)', 
                        borderRadius: 2,
                        cursor: 'pointer',
                        minWidth: 130,
                        bgcolor: 'rgba(0,0,0,0.1)',
                        transition: 'all 0.15s',
                        '&:hover': { 
                          borderColor: 'primary.main',
                          transform: 'translateY(-2px)',
                          bgcolor: 'rgba(0,0,0,0.2)'
                        }
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{pred.ticker}</Typography>
                        <Chip 
                          label={pred.direction}
                          size="small"
                          color={pred.direction === 'Up' ? 'success' : pred.direction === 'Down' ? 'error' : 'default'}
                          sx={{ height: 16, fontSize: '0.65rem', fontWeight: 'bold' }}
                        />
                      </Box>
                      <Typography variant="caption" color="text.secondary">
                        Price: ${pred.current_price.toFixed(1)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5, color: 'primary.main' }}>
                        <Plus size={10} /> Auto-Log
                      </Typography>
                    </Box>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Filter controls */}
            <Box sx={{ display: 'flex', gap: 1.5 }}>
              <TextField 
                placeholder="Filter by ticker..." 
                size="small" 
                value={filterTicker}
                onChange={(e) => setFilterTicker(e.target.value)}
                sx={{ width: 160 }}
              />
              <TextField 
                placeholder="Filter by tag..." 
                size="small" 
                value={filterTag}
                onChange={(e) => setFilterTag(e.target.value)}
                sx={{ width: 160 }}
              />
            </Box>

            {/* Journal list cards */}
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {filteredEntries.length === 0 ? (
                <Box sx={{ py: 8, textAlign: 'center', color: 'text.secondary' }}>
                  <AlertCircle size={32} style={{ opacity: 0.3, marginBottom: 8 }} />
                  <Typography variant="body2">No journal entries found matching filters.</Typography>
                </Box>
              ) : (
                filteredEntries.map((entry) => {
                  const moodIcon = MOOD_ICONS[entry.mood] || '';
                  const tagsList = (entry.tags || '').split(',').filter(Boolean);
                  return (
                    <Card key={entry.id} sx={{ transition: 'border-color 0.2s', '&:hover': { borderColor: 'rgba(255,107,53,0.3)' } }}>
                      <CardContent sx={{ p: 3 }}>
                        <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>{entry.title}</Typography>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                            <span style={{ fontSize: '1.2rem' }}>{moodIcon}</span>
                            <IconButton color="error" size="small" onClick={() => handleDeleteEntry(entry.id)}>
                              <Trash2 size={16} />
                            </IconButton>
                          </Box>
                        </Box>

                        <Box sx={{ display: 'flex', gap: 1.5, mb: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
                          {entry.ticker && (
                            <Chip 
                              label={entry.ticker} 
                              size="small" 
                              color="primary" 
                              onClick={() => navigate(`/predict?ticker=${entry.ticker}`)}
                              sx={{ fontWeight: 'bold', height: 20 }}
                            />
                          )}
                          <Chip 
                            label={entry.trade_type} 
                            size="small" 
                            color={entry.trade_type === 'long' ? 'success' : entry.trade_type === 'short' ? 'error' : 'default'}
                            sx={{ fontWeight: 'bold', height: 20, textTransform: 'uppercase' }}
                          />
                          <Typography variant="caption" color="text.secondary">
                            {new Date(entry.created_at).toLocaleString()}
                          </Typography>
                        </Box>

                        <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                          {entry.body}
                        </Typography>

                        {tagsList.length > 0 && (
                          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 2 }}>
                            {tagsList.map((tag) => (
                              <Typography key={tag} variant="caption" sx={{ color: 'primary.main', fontWeight: 'bold', mr: 0.5 }}>
                                #{tag}
                              </Typography>
                            ))}
                          </Box>
                        )}
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </Box>
          </Grid>
        </Grid>
      )}
    </Box>
  );
};

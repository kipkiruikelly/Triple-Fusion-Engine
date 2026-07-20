import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Search, TrendingUp, TrendingDown, Bell, Eye, BarChart, DollarSign, Activity } from 'lucide-react';
import toast from 'react-hot-toast';
import { 
  Box, Typography, Card, CardContent, TextField, Button, Grid, 
  CircularProgress, InputAdornment, Dialog, DialogTitle, DialogContent, 
  DialogActions, Select, MenuItem, LinearProgress
} from '@mui/material';
import { apiFetch } from '../utils/api';
import { PredictionChart } from '../components/PredictionChart';

interface PriceData {
  price?: number;
  prev?: number;
}

interface InfoData {
  name?: string;
  sector?: string;
  industry?: string;
  market_cap?: number;
  pe?: number;
  eps?: number;
  '52w_high'?: number;
  '52w_low'?: number;
  avg_volume?: number;
  beta?: number;
  div_yield?: number;
  target_mean?: number;
  recommendation?: string;
  analyst_count?: number;
  short_float?: number;
  description?: string;
}

interface NewsItem {
  title: string;
  link: string;
}

interface PredictionData {
  direction?: 'Up' | 'Down' | 'HOLD';
  confidence?: number;
  lr_pred?: number;
  action?: 'BUY' | 'SELL' | 'HOLD';
  rsi?: number;
  macd?: string;
  ict_bias?: string;
  current_price?: number;
  lw_chart_data?: any;
}

interface FeatureItem {
  name: string;
  importance: number;
}

const formatAnalysisText = (text: string) => {
  if (!text) return null;
  const lines = text.split('\n');
  return lines.map((line, idx) => {
    if (!line.trim()) {
      return <Box key={idx} sx={{ height: '12px' }} />;
    }
    const isHeader = line.trim().startsWith('✦');
    let cleanLine = line;
    if (isHeader) {
      cleanLine = line.replace('✦', '').trim();
    }
    const parts = cleanLine.split('**');
    const formattedLine = parts.map((part, pIdx) => {
      if (pIdx % 2 === 1) {
        return <strong key={pIdx} style={{ color: '#fff', fontWeight: 'bold' }}>{part}</strong>;
      }
      return part;
    });

    if (isHeader) {
      return (
        <Typography 
          key={idx} 
          variant="subtitle1" 
          sx={{ 
            fontWeight: 'bold', 
            color: 'primary.main', 
            mt: idx > 0 ? 3 : 1, 
            mb: 1.5, 
            display: 'block',
            fontSize: '0.95rem',
            letterSpacing: '0.02em'
          }}
        >
          ✦ {formattedLine}
        </Typography>
      );
    }
    
    return (
      <Typography 
        key={idx} 
        variant="body2" 
        sx={{ 
          lineHeight: 1.7, 
          color: 'text.secondary', 
          mb: 1.5, 
          display: 'block' 
        }}
      >
        {formattedLine}
      </Typography>
    );
  });
};

export const ResearchDashboard: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryTicker = searchParams.get('ticker') || '';

  const [ticker, setTicker] = useState(queryTicker || 'AAPL');
  const [activeTicker, setActiveTicker] = useState('');
  const [loading, setLoading] = useState(false);

  // Loaded details
  const [priceData, setPriceData] = useState<PriceData>({});
  const [infoData, setInfoData] = useState<InfoData>({});
  const [newsList, setNewsList] = useState<NewsItem[]>([]);
  const [prediction, setPrediction] = useState<PredictionData>({});

  // AI commentary
  const [aiAnalysis, setAiAnalysis] = useState('');
  const [generatingAi, setGeneratingAi] = useState(false);

  // Modals state
  const [ptOpen, setPtOpen] = useState(false);
  const [ptSide, setPtSide] = useState<'long' | 'short'>('long');
  const [ptPrice, setPtPrice] = useState('');
  const [ptQty, setPtQty] = useState('10');
  const [submittingPt, setSubmittingPt] = useState(false);

  const [featOpen, setFeatOpen] = useState(false);
  const [features, setFeatures] = useState<FeatureItem[]>([]);
  const [loadingFeat, setLoadingFeat] = useState(false);

  const fetchResearch = useCallback(async (t: string) => {
    if (!t) return;
    setLoading(true);
    setAiAnalysis(''); // Clear AI commentary when switching tickers
    try {
      const json = await apiFetch(`/api/research/${t}`);
      if (json.ok && json.data) {
        setPriceData(json.data.price || {});
        setInfoData(json.data.info || {});
        setNewsList(json.data.news || []);
        setPrediction(json.data.prediction || {});
        setActiveTicker(t);
      } else {
        toast.error(json.error || 'Failed to load research analytics');
      }
    } catch (err) {
      toast.error('Network connection error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (queryTicker) {
      setTicker(queryTicker);
      fetchResearch(queryTicker);
    } else {
      fetchResearch('AAPL');
    }
  }, [queryTicker, fetchResearch]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (ticker.trim()) {
      fetchResearch(ticker.trim().toUpperCase());
    }
  };

  // Action: Predict ML Model
  const runPredictionModel = async () => {
    if (!activeTicker) return;
    setLoading(true);
    try {
      const res = await apiFetch('/api/predict', {
        method: 'POST',
        body: { ticker: activeTicker, interval: '1d' }
      });
      if (res.ok) {
        setPrediction(res);
        toast.success('ML Model predictions updated!');
      } else {
        toast.error(res.error || 'Failed to run prediction');
      }
    } catch (err) {
      toast.error('Failed to run ML model');
    } finally {
      setLoading(false);
    }
  };

  // Action: Watchlist toggle
  const handleWatchlistAdd = async () => {
    if (!activeTicker) return;
    try {
      const res = await apiFetch('/api/watchlist', {
        method: 'POST',
        body: { ticker: activeTicker }
      });
      if (res.ok) {
        toast.success(`${activeTicker} added to watchlist!`);
      } else {
        toast.error(res.error || 'Failed to add to watchlist');
      }
    } catch (err) {
      toast.error('Failed to update watchlist');
    }
  };

  // Action: Open paper trade modal
  const handleOpenPaperTrade = () => {
    setPtPrice(priceData.price ? priceData.price.toString() : '');
    setPtSide(prediction.direction === 'Down' ? 'short' : 'long');
    setPtOpen(true);
  };

  // Action: Log paper trade position
  const handleSubmitPaperTrade = async () => {
    setSubmittingPt(true);
    try {
      const res = await apiFetch('/api/portfolio/open', {
        method: 'POST',
        body: {
          ticker: activeTicker,
          side: ptSide,
          entry_price: parseFloat(ptPrice),
          quantity: parseFloat(ptQty),
          note: `Logged from Research hub (${prediction.direction || 'Hold'} signal)`
        }
      });
      if (res.ok) {
        toast.success('Paper trade logged successfully!');
        setPtOpen(false);
      } else {
        toast.error(res.error || 'Failed to submit trade');
      }
    } catch (err) {
      toast.error('Failed to record position');
    } finally {
      setSubmittingPt(false);
    }
  };

  // Action: Load Feature Drivers
  const handleOpenFeatures = async () => {
    setFeatOpen(true);
    setLoadingFeat(true);
    try {
      const json = await apiFetch(`/api/feature-importance/${activeTicker}?interval=1d`);
      if (json.ok && json.features) {
        setFeatures(json.features);
      } else {
        setFeatures([]);
        toast.error(json.error || 'No feature drivers found for this model');
      }
    } catch (err) {
      toast.error('Failed to load model drivers');
    } finally {
      setLoadingFeat(false);
    }
  };

  // Action: AI Commentary
  const generateAiCommentary = async () => {
    setGeneratingAi(true);
    try {
      const res = await apiFetch(`/api/ai/analyze/${activeTicker}`, {
        method: 'POST',
        body: {
          interval: '1d',
          current_price: prediction.current_price || priceData.price || 0,
          lr_pred: prediction.lr_pred,
          direction: prediction.direction || '-',
          confidence: prediction.confidence || 0,
          rsi: prediction.rsi || 50,
          macd_signal: prediction.macd || '-',
          ict_bias: prediction.ict_bias || '-'
        }
      });
      if (res.ok && res.analysis) {
        setAiAnalysis(res.analysis);
        toast.success('AI market commentary compiled!');
      } else {
        toast.error(res.error || 'AI analysis is currently unavailable');
      }
    } catch (err) {
      toast.error('Failed to generate commentary');
    } finally {
      setGeneratingAi(false);
    }
  };

  // Helper values
  const pctChange = priceData.price && priceData.prev 
    ? ((priceData.price - priceData.prev) / priceData.prev) * 100 
    : 0;

  const analystUpside = infoData.target_mean && priceData.price 
    ? ((infoData.target_mean / priceData.price) - 1) * 100 
    : null;

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Search Input block */}
      <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: '8px', width: '100%', maxWidth: 460 }}>
          <TextField 
            placeholder="Search ticker (e.g. AAPL, MSFT, TSLA)"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            size="small"
            fullWidth
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <Search size={16} />
                  </InputAdornment>
                )
              }
            }}
          />
          <Button type="submit" variant="contained" color="primary" sx={{ fontWeight: 'bold', minWidth: 100 }}>
            Research
          </Button>
        </form>
      </Box>

      {loading && !activeTicker ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 10, gap: 2 }}>
          <CircularProgress />
          <Typography color="text.secondary">Running research on {ticker}...</Typography>
        </Box>
      ) : !activeTicker ? (
        <Box sx={{ py: 10, textAlign: 'center', color: 'text.secondary' }}>
          Enter a stock ticker symbol above to start deep quantitative research.
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Company Details strip */}
          <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 2 }}>
            <Box>
              <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'flex', alignItems: 'center', gap: 1 }}>
                {activeTicker}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {infoData.name || activeTicker} · {infoData.sector || '—'} · {infoData.industry || '—'}
              </Typography>
            </Box>
            {priceData.price !== undefined && (
              <Box sx={{ textAlign: 'right' }}>
                <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                  ${priceData.price.toFixed(2)}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 'bold', color: pctChange >= 0 ? 'success.main' : 'error.main', mt: 0.5 }}>
                  {pctChange >= 0 ? '+' : ''}{pctChange.toFixed(2)}% today
                </Typography>
              </Box>
            )}
          </Box>

          {/* Action Toolbar */}
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Button 
              variant="contained" 
              color="primary" 
              onClick={runPredictionModel} 
              startIcon={<Activity size={16} />}
              sx={{ fontWeight: 'bold' }}
            >
              Run ML Prediction
            </Button>
            <Button 
              variant="outlined" 
              onClick={handleOpenPaperTrade} 
              startIcon={<DollarSign size={16} />}
              sx={{ fontWeight: 'bold' }}
            >
              Paper Trade
            </Button>
            <Button 
              variant="outlined" 
              onClick={() => navigate('/alerts')} 
              startIcon={<Bell size={16} />}
              sx={{ fontWeight: 'bold' }}
            >
              Set Alert
            </Button>
            <Button 
              variant="outlined" 
              onClick={handleOpenFeatures} 
              startIcon={<BarChart size={16} />}
              sx={{ fontWeight: 'bold' }}
            >
              Feature Drivers
            </Button>
            <Button 
              variant="outlined" 
              onClick={handleWatchlistAdd} 
              startIcon={<Eye size={16} />}
              sx={{ fontWeight: 'bold' }}
            >
              Watchlist
            </Button>
          </Box>

          {/* Prediction banner details */}
          {prediction.direction && (
            <Card sx={{ 
              border: '1px solid', 
              borderColor: prediction.direction === 'Up' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
              bgcolor: prediction.direction === 'Up' ? 'rgba(16, 185, 129, 0.03)' : 'rgba(239, 68, 68, 0.03)'
            }}>
              <CardContent sx={{ p: 3 }}>
                <Grid container spacing={3} sx={{ alignItems: 'center' }}>
                  <Grid size={{ xs: 12, md: 4 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>ML Direction Signal</Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                      {prediction.direction === 'Up' ? (
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'success.main', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <TrendingUp size={24} /> Bullish
                        </Typography>
                      ) : (
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'error.main', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <TrendingDown size={24} /> Bearish
                        </Typography>
                      )}
                    </Box>
                    {prediction.lr_pred && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        Predicted Close: <strong>${prediction.lr_pred.toFixed(2)}</strong>
                      </Typography>
                    )}
                  </Grid>

                  <Grid size={{ xs: 12, md: 4 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>Signal Confidence</Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 1 }}>
                      <LinearProgress 
                        variant="determinate" 
                        value={prediction.confidence || 0}
                        sx={{ 
                          flex: 1,
                          height: 6, 
                          borderRadius: 3, 
                          bgcolor: 'rgba(255,255,255,0.05)',
                          '& .MuiLinearProgress-bar': {
                            bgcolor: prediction.direction === 'Up' ? 'success.main' : 'error.main'
                          }
                        }}
                      />
                      <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                        {prediction.confidence?.toFixed(0)}%
                      </Typography>
                    </Box>
                  </Grid>

                  <Grid size={{ xs: 12, md: 4 }}>
                    <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', borderLeft: { md: '1px solid rgba(255,255,255,0.05)' }, pl: { md: 3 } }}>
                      <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>RSI (14)</Typography>
                        <Typography variant="body1" sx={{ 
                          fontWeight: 'bold', 
                          mt: 0.5,
                          color: prediction.rsi !== undefined && prediction.rsi >= 70 ? 'error.main' : prediction.rsi !== undefined && prediction.rsi <= 30 ? 'success.main' : 'text.primary'
                        }}>
                          {prediction.rsi?.toFixed(1) || '—'}
                        </Typography>
                      </Box>
                      <Box sx={{ textAlign: 'right' }}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>MACD / Bias</Typography>
                        <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold', mt: 0.5, color: 'text.primary' }}>
                          MACD: {prediction.macd || '—'}
                        </Typography>
                        <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                          ICT: {prediction.ict_bias || '—'}
                        </Typography>
                      </Box>
                    </Box>
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          )}

          {prediction.direction && prediction.lw_chart_data && (
            <PredictionChart data={prediction.lw_chart_data} ticker={activeTicker} />
          )}

          {/* Fundamentals stats grid */}
          <Grid container spacing={2}>
            {[
              { label: 'Market Cap', val: infoData.market_cap ? (infoData.market_cap >= 1e12 ? `$${(infoData.market_cap/1e12).toFixed(2)}T` : infoData.market_cap >= 1e9 ? `$${(infoData.market_cap/1e9).toFixed(2)}B` : `$${infoData.market_cap.toLocaleString()}`) : '—' },
              { label: 'P/E Ratio', val: infoData.pe?.toFixed(2) || '—' },
              { label: 'Beta', val: infoData.beta?.toFixed(2) || '—' },
              { label: 'Short Float', val: infoData.short_float ? `${infoData.short_float}%` : '—' },
              { label: '52W High', val: infoData['52w_high'] ? `$${infoData['52w_high'].toFixed(2)}` : '—' },
              { label: '52W Low', val: infoData['52w_low'] ? `$${infoData['52w_low'].toFixed(2)}` : '—' },
              { label: 'Dividend Yield', val: infoData.div_yield ? `${infoData.div_yield}%` : '—' },
              { label: 'EPS', val: infoData.eps ? `$${infoData.eps.toFixed(2)}` : '—' }
            ].map((stat, i) => (
              <Grid key={i} size={{ xs: 6, sm: 3 }}>
                <Box sx={{ p: 1.8, bgcolor: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.03)', borderRadius: 2 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'medium', display: 'block' }}>{stat.label}</Typography>
                  <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>{stat.val}</Typography>
                </Box>
              </Grid>
            ))}
          </Grid>

          {/* Detailed Splits: News, Consensus, About */}
          <Grid container spacing={3}>
            {/* News bulletins */}
            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: '100%' }}>
                <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Latest News</Typography>
                </Box>
                <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                  {newsList.length === 0 ? (
                    <Typography color="text.secondary" variant="body2">No recent news available.</Typography>
                  ) : (
                    newsList.map((n, idx) => (
                      <Box key={idx} sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
                        <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'primary.main', mt: 1, flexShrink: 0 }} />
                        <a href={n.link} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none' }}>
                          <Typography variant="body2" color="text.primary" sx={{ 
                            lineHeight: 1.4,
                            '&:hover': { color: 'primary.main', textDecoration: 'underline' }
                          }}>
                            {n.title}
                          </Typography>
                        </a>
                      </Box>
                    ))
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* Consensus & Description */}
            <Grid size={{ xs: 12, md: 6 }} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {/* Analyst Consensus */}
              {infoData.recommendation && (
                <Card>
                  <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Analyst Consensus</Typography>
                  </Box>
                  <CardContent sx={{ p: 3 }}>
                    <Typography variant="h5" sx={{ 
                      fontWeight: 'bold', 
                      color: infoData.recommendation === 'buy' || infoData.recommendation === 'strong_buy' ? 'success.main' : infoData.recommendation === 'sell' ? 'error.main' : 'warning.main',
                      textTransform: 'uppercase'
                    }}>
                      {infoData.recommendation.replace('_', ' ')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Based on {infoData.analyst_count} analysts · Mean Target: <strong>${infoData.target_mean?.toFixed(2)}</strong>
                    </Typography>
                    {analystUpside !== null && (
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        Potential Upside:{' '}
                        <strong style={{ color: analystUpside >= 0 ? '#10b981' : '#ef4444' }}>
                          {analystUpside >= 0 ? '+' : ''}{analystUpside.toFixed(1)}%
                        </strong>
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* About description */}
              <Card sx={{ flex: 1 }}>
                <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Company Overview</Typography>
                </Box>
                <CardContent sx={{ p: 3 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                    {infoData.description || 'No overview description available.'}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* AI Commentary Analysis block */}
          <Card sx={{ 
            border: '1px solid rgba(139, 92, 246, 0.2)',
            bgcolor: 'rgba(139, 92, 246, 0.02)'
          }}>
            <Box sx={{ px: 3, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: 'primary.main' }}>
                ✦ In-Depth AI Market Commentary Analysis
              </Typography>
            </Box>
            <CardContent sx={{ p: 3 }}>
              {aiAnalysis ? (
                formatAnalysisText(aiAnalysis)
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Generate a complete analysis report combining historical price data, volume spikes, and technical metrics indicators.
                </Typography>
              )}
              
              <Button 
                variant="contained" 
                color="primary" 
                disabled={generatingAi}
                onClick={generateAiCommentary}
                sx={{ fontWeight: 'bold', mt: aiAnalysis ? 3 : 0 }}
              >
                {generatingAi ? 'Generating Analysis Commentary...' : aiAnalysis ? 'Re-generate Analysis' : 'Generate Analysis Report'}
              </Button>
            </CardContent>
          </Card>
        </Box>
      )}

      {/* Paper Trading modal */}
      <Dialog open={ptOpen} onClose={() => setPtOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 'bold' }}>Log Paper Trade: {activeTicker}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, mt: 1.5 }}>
            <Select 
              value={ptSide} 
              onChange={(e) => setPtSide(e.target.value as 'long' | 'short')}
              size="small"
              fullWidth
            >
              <MenuItem value="long">Buy (Long)</MenuItem>
              <MenuItem value="short">Sell (Short)</MenuItem>
            </Select>

            <TextField 
              label="Entry Price"
              type="number"
              value={ptPrice}
              onChange={(e) => setPtPrice(e.target.value)}
              slotProps={{ htmlInput: { step: '0.01' } }}
              size="small"
              fullWidth
            />

            <TextField 
              label="Quantity"
              type="number"
              value={ptQty}
              onChange={(e) => setPtQty(e.target.value)}
              slotProps={{ htmlInput: { step: '1' } }}
              size="small"
              fullWidth
            />
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setPtOpen(false)} color="inherit">Cancel</Button>
          <Button 
            onClick={handleSubmitPaperTrade} 
            variant="contained" 
            color="primary"
            disabled={submittingPt}
          >
            {submittingPt ? 'Logging...' : 'Log Position'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Feature Importance modal */}
      <Dialog open={featOpen} onClose={() => setFeatOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 'bold' }}>Model Drivers & Feature Importance</DialogTitle>
        <DialogContent>
          {loadingFeat ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
          ) : features.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
              No Random Forest model drivers found for {activeTicker}. Make sure professional model retraining has run.
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
              {features.map((f, i) => {
                const maxVal = Math.max(...features.map(x => x.importance), 1);
                const pct = (f.importance / maxVal) * 100;
                return (
                  <Box key={i}>
                    <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="body2" sx={{ fontWeight: 'medium' }}>{f.name}</Typography>
                      <Typography variant="caption" color="text.secondary">{(f.importance * 100).toFixed(2)}%</Typography>
                    </Box>
                    <LinearProgress 
                      variant="determinate" 
                      value={pct}
                      sx={{ height: 5, borderRadius: 2.5 }}
                    />
                  </Box>
                );
              })}
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setFeatOpen(false)} color="inherit">Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

import React, { useState, useEffect } from 'react';
import { Box, Typography, Grid, Card, CardContent, CircularProgress, Button, FormControl, InputLabel, Select, MenuItem, FormGroup, FormControlLabel, Checkbox, TextField } from '@mui/material';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';
import { ShieldCheck, Play, Save, RefreshCw, BarChart2, Terminal } from 'lucide-react';

export const PipelineDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [activeStep, setActiveStep] = useState<string>('');
  
  // Pipeline settings fields
  const [connector, setConnector] = useState('yfinance');
  const [features, setFeatures] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  
  // RF params
  const [rfEstimators, setRfEstimators] = useState(100);
  const [rfDepth, setRfDepth] = useState(10);
  
  // Action inputs
  const [symbol, setSymbol] = useState('SPY');
  const [interval, setInterval] = useState('1d');
  
  // Logs & outputs
  const [consoleLogs, setConsoleLogs] = useState<string>('');
  const [predictionResult, setPredictionResult] = useState<any>(null);

  const fetchConfig = async () => {
    try {
      const data = await apiFetch('/api/pipeline/config');
      if (data.ok && data.config) {
        setConfig(data.config);
        setConnector(data.config.connector || 'yfinance');
        setFeatures(data.config.features || []);
        setModels(data.config.models || []);
        
        const rfParams = data.config.model_params?.random_forest || {};
        setRfEstimators(rfParams.n_estimators || 100);
        setRfDepth(rfParams.max_depth || 10);
      }
    } catch (err) {
      toast.error('Failed to load pipeline configurations');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const handleFeatureToggle = (featName: string) => {
    setFeatures(prev => 
      prev.includes(featName) ? prev.filter(f => f !== featName) : [...prev, featName]
    );
  };

  const handleModelToggle = (modelName: string) => {
    setModels(prev =>
      prev.includes(modelName) ? prev.filter(m => m !== modelName) : [...prev, modelName]
    );
  };

  const handleSaveConfig = async () => {
    try {
      const updatedConfig = {
        ...config,
        connector,
        features,
        models,
        model_params: {
          ...config?.model_params,
          random_forest: {
            n_estimators: Number(rfEstimators),
            max_depth: Number(rfDepth),
            random_state: 42
          }
        }
      };
      
      const res = await apiFetch('/api/pipeline/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: updatedConfig })
      });
      
      if (res.ok) {
        toast.success('Configuration saved successfully!');
        setConfig(updatedConfig);
      } else {
        toast.error(res.error || 'Failed to save configuration');
      }
    } catch (err) {
      toast.error('Error saving pipeline configuration');
    }
  };

  const handleRunPipeline = async (mode: 'ingest' | 'train' | 'predict') => {
    setRunning(true);
    setActiveStep(mode);
    setConsoleLogs(`Starting execution for mode: ${mode.toUpperCase()} on ${symbol} (${interval})...\n`);
    setPredictionResult(null);
    
    try {
      const res = await apiFetch('/api/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, symbol, interval })
      });
      
      if (res.ok) {
        toast.success(`Pipeline step ${mode} completed successfully!`);
        setConsoleLogs(prev => prev + "\n[EXECUTION LOGS]:\n" + (res.logs || 'No logs returned.'));
        if (mode === 'predict' && res.prediction) {
          setPredictionResult(res.prediction);
        }
      } else {
        toast.error(res.error || 'Pipeline execution failed');
        setConsoleLogs(prev => prev + `\n[ERROR]: ${res.error}\n` + (res.logs || ''));
      }
    } catch (err) {
      toast.error('Error executing pipeline subprocess');
      setConsoleLogs(prev => prev + '\n[CRITICAL ERROR]: Subprocess failed or connection timed out.');
    } finally {
      setRunning(false);
      setActiveStep('');
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', py: 8 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box>
        <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
          Tweakable ML Pipeline Dashboard
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Configure, train, and query modular DASE pipeline engines and custom plugins dynamically.
        </Typography>
      </Box>

      <Grid container spacing={4}>
        {/* Left Side: Pipeline Config Panel */}
        <Grid size={{ xs: 12, lg: 5 }}>
          <Card sx={{ bgcolor: 'background.paper', border: '1px solid rgba(255, 255, 255, 0.05)', borderRadius: 2 }}>
            <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                <Save size={18} className="text-violet-400" /> Pipeline Configuration
              </Typography>
              
              {/* Connector */}
              <FormControl size="small" fullWidth>
                <InputLabel>Active Data Connector</InputLabel>
                <Select
                  value={connector}
                  label="Active Data Connector"
                  onChange={(e) => setConnector(e.target.value)}
                >
                  <MenuItem value="yfinance">Yahoo Finance Ingestion</MenuItem>
                  <MenuItem value="csv">Local CSV Ingestion</MenuItem>
                </Select>
              </FormControl>

              {/* Feature Builders */}
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 1, color: 'text.secondary' }}>
                  Feature Engineering Builders
                </Typography>
                <FormGroup>
                  <FormControlLabel 
                    control={<Checkbox checked={features.includes('technical_analysis')} onChange={() => handleFeatureToggle('technical_analysis')} color="primary" />} 
                    label="Technical Analysis Indicators"
                  />
                  <FormControlLabel 
                    control={<Checkbox checked={features.includes('ict_indicators')} onChange={() => handleFeatureToggle('ict_indicators')} color="primary" />} 
                    label="ICT Order Blocks & Fair Value Gaps"
                  />
                  <FormControlLabel 
                    control={<Checkbox checked={features.includes('auxiliary_market_features')} onChange={() => handleFeatureToggle('auxiliary_market_features')} color="primary" />} 
                    label="VIX Aux, Sector RS, Earnings Window"
                  />
                  <FormControlLabel 
                    control={<Checkbox checked={features.includes('custom_momentum')} onChange={() => handleFeatureToggle('custom_momentum')} color="secondary" />} 
                    label="Momentum Builder [Dynamic Plugin]"
                  />
                </FormGroup>
              </Box>

              {/* Model Trainers */}
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 1, color: 'text.secondary' }}>
                  Model Selection
                </Typography>
                <FormGroup>
                  <FormControlLabel 
                    control={<Checkbox checked={models.includes('linear_regression')} onChange={() => handleModelToggle('linear_regression')} color="primary" />} 
                    label="Linear Regression (Next Close Price)"
                  />
                  <FormControlLabel 
                    control={<Checkbox checked={models.includes('random_forest')} onChange={() => handleModelToggle('random_forest')} color="primary" />} 
                    label="Random Forest (Next Return %)"
                  />
                </FormGroup>
              </Box>

              {/* Random Forest Hyperparams */}
              {models.includes('random_forest') && (
                <Box sx={{ borderTop: '1px solid rgba(255, 255, 255, 0.05)', pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Typography variant="caption" sx={{ fontWeight: 800, color: '#8b5cf6', textTransform: 'uppercase' }}>
                    Random Forest Hyperparameters
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <TextField
                      label="N Estimators"
                      type="number"
                      size="small"
                      value={rfEstimators}
                      onChange={(e) => setRfEstimators(Number(e.target.value))}
                      fullWidth
                    />
                    <TextField
                      label="Max Depth"
                      type="number"
                      size="small"
                      value={rfDepth}
                      onChange={(e) => setRfDepth(Number(e.target.value))}
                      fullWidth
                    />
                  </Box>
                </Box>
              )}

              <Button
                variant="contained"
                color="secondary"
                onClick={handleSaveConfig}
                sx={{ mt: 1, fontWeight: 'bold' }}
                fullWidth
              >
                Save Settings Configuration
              </Button>
            </CardContent>
          </Card>
        </Grid>

        {/* Right Side: Execution controls & Terminal logs */}
        <Grid size={{ xs: 12, lg: 7 }} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Action Trigger Card */}
          <Card sx={{ bgcolor: 'background.paper', border: '1px solid rgba(255, 255, 255, 0.05)', borderRadius: 2 }}>
            <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3.5 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                <Play size={18} className="text-emerald-400" /> Pipeline Control Panel
              </Typography>
              
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  label="Ticker Symbol"
                  size="small"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  fullWidth
                />
                <FormControl size="small" fullWidth>
                  <InputLabel>Timeframe</InputLabel>
                  <Select
                    value={interval}
                    label="Timeframe"
                    onChange={(e) => setInterval(e.target.value)}
                  >
                    <MenuItem value="5m">5 Minute (5m)</MenuItem>
                    <MenuItem value="15m">15 Minute (15m)</MenuItem>
                    <MenuItem value="1h">Hourly (1h)</MenuItem>
                    <MenuItem value="1d">Daily (1d)</MenuItem>
                  </Select>
                </FormControl>
              </Box>

              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <Button
                  variant="outlined"
                  onClick={() => handleRunPipeline('ingest')}
                  disabled={running}
                  startIcon={running && activeStep === 'ingest' ? <CircularProgress size={16} /> : <RefreshCw size={16} />}
                  sx={{ flex: 1, minWidth: '140px', fontWeight: 'bold' }}
                >
                  Ingest & Process
                </Button>
                <Button
                  variant="outlined"
                  color="warning"
                  onClick={() => handleRunPipeline('train')}
                  disabled={running}
                  startIcon={running && activeStep === 'train' ? <CircularProgress size={16} /> : <BarChart2 size={16} />}
                  sx={{ flex: 1, minWidth: '140px', fontWeight: 'bold' }}
                >
                  Train Models
                </Button>
                <Button
                  variant="contained"
                  color="success"
                  onClick={() => handleRunPipeline('predict')}
                  disabled={running}
                  startIcon={running && activeStep === 'predict' ? <CircularProgress size={16} /> : <ShieldCheck size={16} />}
                  sx={{ flex: 1, minWidth: '140px', fontWeight: 'bold', textShadow: '0 1px 2px rgba(0,0,0,0.2)' }}
                >
                  Query Predictor
                </Button>
              </Box>
            </CardContent>
          </Card>

          {/* Predictor output result if successful */}
          {predictionResult && (
            <Card sx={{ borderLeft: '4px solid #10b981', bgcolor: 'background.paper', borderRadius: 2 }}>
              <CardContent sx={{ p: 2.5 }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold', color: 'success.main', display: 'block', mb: 1.5, letterSpacing: 1, textTransform: 'uppercase' }}>
                  Model Prediction Output
                </Typography>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 6, md: 3.2 }}>
                    <Typography variant="caption" color="text.secondary">Direction</Typography>
                    <Typography variant="body1" sx={{ fontWeight: 800, color: predictionResult.direction === 'BUY' ? 'success.main' : predictionResult.direction === 'SELL' ? 'error.main' : 'text.primary' }}>
                      {predictionResult.direction}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, md: 2.2 }}>
                    <Typography variant="caption" color="text.secondary">Entry Price</Typography>
                    <Typography variant="body1" sx={{ fontWeight: 'bold' }}>
                      ${parseFloat(predictionResult.entry_price).toFixed(2)}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, md: 2.2 }}>
                    <Typography variant="caption" color="text.secondary">Stop Loss</Typography>
                    <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'error.main' }}>
                      ${parseFloat(predictionResult.stop_price).toFixed(2)}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, md: 2.2 }}>
                    <Typography variant="caption" color="text.secondary">Take Profit</Typography>
                    <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'success.main' }}>
                      ${parseFloat(predictionResult.target_price).toFixed(2)}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, md: 2.2 }}>
                    <Typography variant="caption" color="text.secondary">Confidence</Typography>
                    <Typography variant="body1" sx={{ fontWeight: 'bold', color: '#8b5cf6' }}>
                      {predictionResult.confidence}
                    </Typography>
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          )}

          {/* Console / Subprocess Logs view */}
          <Card sx={{ flex: 1, display: 'flex', flexDirection: 'column', bgcolor: '#0f0f1a', border: '1px solid rgba(255, 255, 255, 0.05)', borderRadius: 2, minHeight: '300px' }}>
            <Box sx={{ p: 2, borderBottom: '1px solid rgba(255, 255, 255, 0.05)', display: 'flex', alignItems: 'center', gap: 1, color: 'text.secondary' }}>
              <Terminal size={16} />
              <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Execution Log Console</Typography>
            </Box>
            <Box sx={{ 
              flex: 1, 
              p: 2, 
              fontFamily: 'monospace', 
              fontSize: '0.8rem', 
              color: '#d1d4dc', 
              overflowY: 'auto', 
              whiteSpace: 'pre-wrap',
              maxHeight: '400px'
            }}>
              {consoleLogs || 'No execution active. Trigger steps above to display dynamic run details...'}
            </Box>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};

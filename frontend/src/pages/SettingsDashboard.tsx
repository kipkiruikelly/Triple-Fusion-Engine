import React, { useState, useEffect } from 'react';
import { 
  User, Bell, MessageSquare, Download, 
  Trash2, Send, RefreshCw, Award, Smartphone, Terminal, Globe
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { 
  Box, Typography, Card, CardContent, TextField, Button, Grid, 
  MenuItem, Tabs, Tab, Divider, Switch, FormControlLabel, 
  Avatar, Chip, LinearProgress, List, ListItem, ListItemText, 
  ListItemSecondaryAction, IconButton, CircularProgress 
} from '@mui/material';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`settings-tabpanel-${index}`}
      aria-labelledby={`settings-tab-${index}`}
      {...other}
    >
      {value === index && (
        <Box sx={{ py: 3 }}>
          {children}
        </Box>
      )}
    </div>
  );
}

export const SettingsDashboard: React.FC = () => {
  const { user, logout, checkAuth } = useAuth();
  const [tabValue, setTabValue] = useState(0);

  // Profile Form States
  const [theme, setTheme] = useState(user?.theme_preference || 'dark');
  const [usageNotice, setUsageNotice] = useState(false);

  // Security Form States
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  // 2FA States
  const [twoFaStatus, setTwoFaStatus] = useState<any>({ available: false, enabled: false });
  const [twoFaSecret, setTwoFaSecret] = useState('');
  const [twoFaQrUrl, setTwoFaQrUrl] = useState('');
  const [twoFaSetupCode, setTwoFaSetupCode] = useState('');
  const [showTwoFaSetup, setShowTwoFaSetup] = useState(false);
  const [twoFaDisablePassword, setTwoFaDisablePassword] = useState('');
  const [twoFaDisableCode, setTwoFaDisableCode] = useState('');

  // Alerts States
  const [tgStatus, setTgStatus] = useState<any>({ configured: false, chat_id: '' });
  const [tgChatId, setTgChatId] = useState('');
  const [waStatus, setWaStatus] = useState<any>({ configured: false, phone_number: '' });
  const [waPhone, setWaPhone] = useState('');
  const [discordStatus, setDiscordStatus] = useState<any>({ configured: false, enabled: false });
  const [discordWebhookUrl, setDiscordWebhookUrl] = useState('');

  // Developer States
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [apiKeyName, setApiKeyName] = useState('');
  const [newlyCreatedKey, setNewlyCreatedKey] = useState('');
  const [webhooks, setWebhooks] = useState<any[]>([]);
  const [webhookName, setWebhookName] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');

  // Accuracy States
  const [accuracyStats, setAccuracyStats] = useState<any>(null);
  const [loadingAccuracy, setLoadingAccuracy] = useState(false);

  // Gift & Digest States
  const [giftCode, setGiftCode] = useState('');
  const [sendingDigest, setSendingDigest] = useState(false);

  // Loading States
  const [loadingKeys, setLoadingKeys] = useState(false);
  const [loadingWebhooks, setLoadingWebhooks] = useState(false);

  useEffect(() => {
    // Load Preferences
    const fetchPrefs = async () => {
      try {
        const res = await apiFetch('/api/preferences');
        if (res.ok) {
          setUsageNotice(!!res.usage_notice_enabled);
        }
      } catch (err) {
        console.error(err);
      }
    };
    
    // Load 2FA Status
    const fetch2FA = async () => {
      try {
        const res = await apiFetch('/api/2fa/status');
        setTwoFaStatus(res);
      } catch (err) {
        console.error(err);
      }
    };

    // Load Alert Statuses
    const fetchAlerts = async () => {
      try {
        const tg = await apiFetch('/api/telegram/status');
        setTgStatus(tg);
        if (tg.chat_id) setTgChatId(tg.chat_id);

        const wa = await apiFetch('/api/whatsapp/status');
        setWaStatus(wa);
        if (wa.phone_number) setWaPhone(wa.phone_number);

        const dc = await apiFetch('/api/discord/status');
        setDiscordStatus(dc);
      } catch (err) {
        console.error(err);
      }
    };

    if (user) {
      fetchPrefs();
      fetch2FA();
      fetchAlerts();
    }
  }, [user]);

  // Load API Keys
  const loadApiKeys = async () => {
    setLoadingKeys(true);
    try {
      const res = await apiFetch('/api/keys');
      if (Array.isArray(res)) {
        setApiKeys(res);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingKeys(false);
    }
  };

  // Load Webhooks
  const loadWebhooks = async () => {
    setLoadingWebhooks(true);
    try {
      const res = await apiFetch('/api/webhooks');
      if (res.ok && res.webhooks) {
        setWebhooks(res.webhooks);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingWebhooks(false);
    }
  };

  // Load Accuracy stats
  const loadAccuracy = async () => {
    setLoadingAccuracy(true);
    try {
      const res = await apiFetch('/api/accuracy');
      if (res.ok) {
        setAccuracyStats(res);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingAccuracy(false);
    }
  };

  // Watch for developers tab to trigger loads
  useEffect(() => {
    if (tabValue === 2) {
      loadApiKeys();
      loadWebhooks();
    } else if (tabValue === 3) {
      loadAccuracy();
    }
  }, [tabValue]);

  // Update Theme preference
  const handleUpdateTheme = async (v: string) => {
    setTheme(v);
    const res = await apiFetch('/api/settings', {
      method: 'POST',
      body: { theme_preference: v }
    });
    if (res.ok) {
      toast.success('Theme preference saved');
      checkAuth();
    }
  };

  // Update Usage Notice Preference
  const handleToggleUsageNotice = async (v: boolean) => {
    setUsageNotice(v);
    await apiFetch('/api/preferences', {
      method: 'POST',
      body: { usage_notice_enabled: v }
    });
  };

  // Update Password
  const handleUpdatePassword = async () => {
    if (!currentPassword || !newPassword || !confirmPassword) {
      toast.error('Please fill out all password fields');
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error('New passwords do not match');
      return;
    }
    const res = await apiFetch('/api/profile/change-password', {
      method: 'POST',
      body: { 
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword
      }
    });
    if (res.ok) {
      toast.success('Password updated successfully');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } else {
      toast.error(res.error || 'Failed to update password');
    }
  };

  // Setup 2FA View
  const handleSetup2FA = async () => {
    const res = await apiFetch('/api/2fa/setup');
    if (res.ok) {
      setTwoFaSecret(res.secret);
      setTwoFaQrUrl(`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(res.provisioning_uri)}`);
      setShowTwoFaSetup(true);
    } else {
      toast.error(res.error || 'Failed to initialize 2FA');
    }
  };

  // Enable 2FA
  const handleEnable2FA = async () => {
    const res = await apiFetch('/api/2fa/enable', {
      method: 'POST',
      body: { code: twoFaSetupCode }
    });
    if (res.ok) {
      toast.success('2FA successfully enabled!');
      setShowTwoFaSetup(false);
      setTwoFaSetupCode('');
      setTwoFaStatus((prev: any) => ({ ...prev, enabled: true }));
    } else {
      toast.error(res.error || 'Invalid authentication code');
    }
  };

  // Disable 2FA
  const handleDisable2FA = async () => {
    const res = await apiFetch('/api/2fa/disable', {
      method: 'POST',
      body: { code: twoFaDisableCode, password: twoFaDisablePassword }
    });
    if (res.ok) {
      toast.success('2FA disabled successfully.');
      setTwoFaDisablePassword('');
      setTwoFaDisableCode('');
      setTwoFaStatus((prev: any) => ({ ...prev, enabled: false }));
    } else {
      toast.error(res.error || 'Incorrect code or password');
    }
  };

  // Telegram save
  const handleSaveTelegram = async () => {
    if (!tgChatId) {
      toast.error('Chat ID is required');
      return;
    }
    const res = await apiFetch('/api/telegram/configure', {
      method: 'POST',
      body: { chat_id: tgChatId, enabled: true }
    });
    if (res.ok) {
      toast.success('Telegram Connected!');
      setTgStatus({ configured: true, chat_id: tgChatId });
    } else {
      toast.error(res.error || 'Failed to configure Telegram');
    }
  };

  // Telegram remove
  const handleRemoveTelegram = async () => {
    const res = await apiFetch('/api/telegram/remove', { method: 'POST' });
    if (res.ok) {
      toast.success('Telegram alerts disconnected');
      setTgStatus({ configured: false, chat_id: '' });
      setTgChatId('');
    }
  };

  // WhatsApp configure
  const handleSaveWhatsapp = async () => {
    if (!waPhone) {
      toast.error('Phone number is required');
      return;
    }
    const res = await apiFetch('/api/whatsapp/configure', {
      method: 'POST',
      body: { phone_number: waPhone, enabled: true }
    });
    if (res.ok) {
      toast.success('WhatsApp Connected!');
      setWaStatus({ configured: true, phone_number: waPhone });
    } else {
      toast.error(res.error || 'Failed to configure WhatsApp');
    }
  };

  // WhatsApp remove
  const handleRemoveWhatsapp = async () => {
    const res = await apiFetch('/api/whatsapp/remove', { method: 'POST' });
    if (res.ok) {
      toast.success('WhatsApp alerts disconnected');
      setWaStatus({ configured: false, phone_number: '' });
      setWaPhone('');
    }
  };

  // Discord configure
  const handleSaveDiscord = async () => {
    if (!discordWebhookUrl) {
      toast.error('Webhook URL required');
      return;
    }
    const res = await apiFetch('/api/discord/configure', {
      method: 'POST',
      body: { webhook_url: discordWebhookUrl }
    });
    if (res.ok) {
      toast.success('Discord Webhook Configured!');
      setDiscordStatus({ configured: true, enabled: true });
    } else {
      toast.error(res.error || 'Failed to configure Discord');
    }
  };

  // Discord remove
  const handleRemoveDiscord = async () => {
    const res = await apiFetch('/api/discord/remove', { method: 'POST' });
    if (res.ok) {
      toast.success('Discord disconnected');
      setDiscordStatus({ configured: false, enabled: false });
      setDiscordWebhookUrl('');
    }
  };

  // Discord test
  const handleTestDiscord = async () => {
    const res = await apiFetch('/api/discord/test', { method: 'POST' });
    if (res.ok) {
      toast.success('Discord test alert sent!');
    } else {
      toast.error(res.error || 'Failed to send test alert');
    }
  };

  // API Key creation
  const handleCreateApiKey = async () => {
    if (!apiKeyName) {
      toast.error('Please enter a key name');
      return;
    }
    const res = await apiFetch('/api/keys/create', {
      method: 'POST',
      body: { name: apiKeyName }
    });
    if (res.ok) {
      setNewlyCreatedKey(res.key);
      setApiKeyName('');
      loadApiKeys();
      toast.success('API Key created successfully!');
    } else {
      toast.error(res.error || 'Failed to create API key');
    }
  };

  // API Key revoke
  const handleRevokeApiKey = async (id: number) => {
    if (!window.confirm('Are you sure you want to revoke this API key? This cannot be undone.')) return;
    const res = await apiFetch('/api/keys/delete', {
      method: 'POST',
      body: { key_id: id }
    });
    if (res.ok) {
      toast.success('API Key revoked');
      loadApiKeys();
    }
  };

  // Custom Webhook add
  const handleAddWebhook = async () => {
    if (!webhookUrl || !webhookName) {
      toast.error('Name and URL are required');
      return;
    }
    const res = await apiFetch('/api/webhooks/add', {
      method: 'POST',
      body: { name: webhookName, url: webhookUrl }
    });
    if (res.ok) {
      toast.success('Custom webhook registered!');
      setWebhookName('');
      setWebhookUrl('');
      loadWebhooks();
    } else {
      toast.error(res.error || 'Failed to add webhook');
    }
  };

  // Custom Webhook delete
  const handleDeleteWebhook = async (id: number) => {
    if (!window.confirm('Delete this webhook?')) return;
    const res = await apiFetch('/api/webhooks/delete', {
      method: 'POST',
      body: { webhook_id: id }
    });
    if (res.ok) {
      toast.success('Webhook deleted');
      loadWebhooks();
    }
  };

  // Webhook test
  const handleTestWebhook = async (id: number) => {
    const res = await apiFetch('/api/webhooks/test', {
      method: 'POST',
      body: { webhook_id: id }
    });
    if (res.ok) {
      toast.success('Test payload queued to fire!');
      loadWebhooks();
    } else {
      toast.error(res.error || 'Test fire failed');
    }
  };

  // Redeem gift code
  const handleRedeemGift = async () => {
    if (!giftCode) {
      toast.error('Enter a gift code first');
      return;
    }
    const res = await apiFetch('/api/gift/redeem', {
      method: 'POST',
      body: { code: giftCode.trim().toUpperCase() }
    });
    if (res.ok) {
      toast.success(`Redeemed code successfully! Plan is now ${res.plan}`);
      setGiftCode('');
      checkAuth();
    } else {
      toast.error(res.error || 'Invalid or expired gift code');
    }
  };

  // Send Daily Digest
  const handleSendDigest = async () => {
    setSendingDigest(true);
    try {
      const res = await apiFetch('/api/digest/send', { method: 'POST' });
      if (res.ok) {
        toast.success('Daily morning digest email sent successfully!');
      } else {
        toast.error(res.error || 'Failed to send digest');
      }
    } catch (err) {
      toast.error('Failed to send request');
    } finally {
      setSendingDigest(false);
    }
  };

  // Delete account
  const handleDeleteAccount = async () => {
    if (!window.confirm('WARNING: Permanently delete your BullLogic account? This action is immediate and cannot be undone.')) return;
    const res = await apiFetch('/api/account/delete', {
      method: 'POST',
      body: { confirm: true }
    });
    if (res.ok) {
      toast.success('Account deleted.');
      logout();
    } else {
      toast.error(res.error || 'Account deletion failed.');
    }
  };

  const getAccuracyColor = (accuracy: number | null) => {
    if (accuracy === null) return '#7a8499';
    if (accuracy >= 75) return '#10b981';
    if (accuracy >= 55) return '#8b5cf6';
    return '#ef4444';
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* Profile Header Card */}
      <Card sx={{ 
        background: 'linear-gradient(135deg, rgba(30, 33, 40, 0.9) 0%, rgba(22, 24, 29, 0.9) 100%)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 3
      }}>
        <CardContent sx={{ p: 4 }}>
          <Grid container spacing={3} sx={{ alignItems: 'center' }}>
            <Grid size={{ xs: 12, md: 'auto' }} sx={{ display: 'flex', justifyContent: 'center' }}>
              <Avatar sx={{ 
                width: 80, 
                height: 80, 
                bgcolor: 'primary.main', 
                color: '#fff',
                fontSize: '2rem', 
                fontWeight: 'bold',
                boxShadow: '0 0 20px rgba(139, 92, 246, 0.3)'
              }}>
                {user?.username ? user.username[0].toUpperCase() : 'U'}
              </Avatar>
            </Grid>
            <Grid size={{ xs: 12, md: 7 }}>
              <Box sx={{ textAlign: { xs: 'center', md: 'left' } }}>
                <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                  {user?.username}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {user?.email}
                </Typography>
                <Box sx={{ mt: 1.5, display: 'flex', gap: 1, justifyContent: { xs: 'center', md: 'flex-start' } }}>
                  <Chip 
                    label={user?.is_pro ? 'Pro Tier' : user?.is_plus ? 'Plus Tier' : 'Free Tier'} 
                    color="primary" 
                    size="small" 
                    sx={{ fontWeight: 'bold' }}
                  />
                  <Chip 
                    label="BullLogic Member" 
                    variant="outlined" 
                    size="small" 
                    sx={{ color: 'text.secondary', borderColor: 'rgba(255,255,255,0.1)' }}
                  />
                </Box>
              </Box>
            </Grid>
            <Grid size={{ xs: 12, md: 'auto' }}>
              <Box sx={{ textAlign: { xs: 'center', md: 'right' } }}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                  Predictions remaining today
                </Typography>
                <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'primary.main', mt: 0.5 }}>
                  {user?.is_plus || user?.is_pro ? '∞' : `${user?.predictions_remaining ?? 5}/5`}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                  {user?.is_plus || user?.is_pro ? 'Unlimited predictions' : 'Daily quota'}
                </Typography>
              </Box>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* Gamification progress */}
      {user && (
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card>
              <CardContent sx={{ p: 3 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Award size={18} color="#8b5cf6" /> Level {user.level}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {user.xp} XP total ({user.xp_into_level}/100)
                  </Typography>
                </Box>
                <LinearProgress 
                  variant="determinate" 
                  value={user.xp_into_level || 0} 
                  sx={{ height: 6, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.05)' }}
                />
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  {100 - (user.xp_into_level || 0)} XP needed to reach Level {user.level + 1}
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }}>
            <Card>
              <CardContent sx={{ p: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
                <Typography variant="h3" sx={{ fontSize: '2.2rem' }}>🔥</Typography>
                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                    Activity Streak
                  </Typography>
                  <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'primary.main', mt: 0.2 }}>
                    {user.current_streak || 0} day{user.current_streak === 1 ? '' : 's'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Best: {user.longest_streak || 0} days
                  </Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Tab Area */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs 
          value={tabValue} 
          onChange={(_, val) => setTabValue(val)} 
          variant="scrollable"
          scrollButtons="auto"
          aria-label="settings tabs"
        >
          <Tab label="Profile & Security" icon={<User size={16} />} iconPosition="start" />
          <Tab label="Alert Channels" icon={<Bell size={16} />} iconPosition="start" />
          <Tab label="Developers" icon={<Terminal size={16} />} iconPosition="start" />
          <Tab label="Accuracy & Settings" icon={<Award size={16} />} iconPosition="start" />
        </Tabs>
      </Box>

      {/* Profile & Security Tab */}
      <TabPanel value={tabValue} index={0}>
        <Grid container spacing={3}>
          {/* Account Details */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  Account Information
                </Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
                  <TextField 
                    label="Username" 
                    size="small" 
                    value={user?.username || ''} 
                    slotProps={{ input: { readOnly: true } }} 
                    fullWidth 
                  />
                  <TextField 
                    label="Email Address" 
                    size="small" 
                    value={user?.email || ''} 
                    slotProps={{ input: { readOnly: true } }} 
                    fullWidth 
                  />
                  <TextField 
                    label="Account ID" 
                    size="small" 
                    value={`#${user?.id || ''}`} 
                    slotProps={{ input: { readOnly: true } }} 
                    fullWidth 
                  />
                  <TextField 
                    label="Account Subscription Tier" 
                    size="small" 
                    value={user?.is_pro ? 'PRO — Unlimited model and API access' : user?.is_plus ? 'PLUS — Unlimited predictions' : 'FREE Tier'} 
                    slotProps={{ input: { readOnly: true } }} 
                    fullWidth 
                  />
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Change Password */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  Change Password
                </Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <TextField 
                    id="pw-current"
                    label="Current Password" 
                    type="password" 
                    size="small" 
                    value={currentPassword} 
                    onChange={(e) => setCurrentPassword(e.target.value)} 
                    fullWidth 
                  />
                  <TextField 
                    id="pw-new"
                    label="New Password" 
                    type="password" 
                    size="small" 
                    value={newPassword} 
                    onChange={(e) => setNewPassword(e.target.value)} 
                    fullWidth 
                  />
                  <TextField 
                    id="pw-confirm"
                    label="Confirm New Password" 
                    type="password" 
                    size="small" 
                    value={confirmPassword} 
                    onChange={(e) => setConfirmPassword(e.target.value)} 
                    fullWidth 
                  />
                  <Button 
                    id="pw-update-btn"
                    variant="contained" 
                    color="primary" 
                    onClick={handleUpdatePassword}
                    sx={{ alignSelf: 'flex-start', fontWeight: 'bold' }}
                  >
                    Update Password
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* 2FA Card */}
          <Grid size={12}>
            <Card>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
                  <Box>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                      Two-Factor Authentication (2FA)
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      Secure your account by requiring an authenticator code (like Google Authenticator or Authy) on login.
                    </Typography>
                  </Box>
                  <Box>
                    {twoFaStatus.enabled ? (
                      <Chip label="Enabled" color="success" sx={{ fontWeight: 'bold' }} />
                    ) : (
                      <Chip label="Disabled" color="default" sx={{ fontWeight: 'bold' }} />
                    )}
                  </Box>
                </Box>

                {!twoFaStatus.enabled && !showTwoFaSetup && (
                  <Button 
                    id="2fa-setup-btn"
                    variant="contained" 
                    color="primary" 
                    onClick={handleSetup2FA}
                    sx={{ alignSelf: 'flex-start', fontWeight: 'bold' }}
                  >
                    Set Up 2FA
                  </Button>
                )}

                {showTwoFaSetup && (
                  <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 4, p: 2.5, bgcolor: 'rgba(0,0,0,0.15)', borderRadius: 2 }}>
                    {twoFaQrUrl && (
                      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
                        <img src={twoFaQrUrl} alt="2FA QR Code" style={{ border: '2px solid rgba(255,255,255,0.05)', borderRadius: '8px' }} />
                        <Typography variant="caption" color="text.secondary">Scan this QR Code</Typography>
                      </Box>
                    )}
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                        Or enter this secret key manually:
                      </Typography>
                      <code style={{ background: 'rgba(255,255,255,0.05)', padding: '6px 12px', borderRadius: '4px', display: 'inline-block', width: 'fit-content', letterSpacing: 1.5 }}>
                        {twoFaSecret}
                      </code>
                      <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                        <TextField 
                          id="2fa-setup-code"
                          label="Enter 6-digit App Code" 
                          size="small" 
                          value={twoFaSetupCode} 
                          onChange={(e) => setTwoFaSetupCode(e.target.value)} 
                          sx={{ maxWidth: 200 }}
                        />
                        <Button 
                          id="2fa-enable-btn"
                          variant="contained" 
                          color="success" 
                          onClick={handleEnable2FA}
                          sx={{ fontWeight: 'bold' }}
                        >
                          Verify & Enable
                        </Button>
                      </Box>
                    </Box>
                  </Box>
                )}

                {twoFaStatus.enabled && (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 2.5, bgcolor: 'rgba(255,77,77,0.02)', border: '1px solid rgba(255,77,77,0.1)', borderRadius: 2 }}>
                    <Typography variant="subtitle2" sx={{ color: 'error.main', fontWeight: 'bold' }}>
                      Disable 2FA Configuration
                    </Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                      <TextField 
                        id="2fa-disable-pw"
                        label="Password" 
                        type="password" 
                        size="small" 
                        value={twoFaDisablePassword} 
                        onChange={(e) => setTwoFaDisablePassword(e.target.value)} 
                      />
                      <TextField 
                        id="2fa-disable-code"
                        label="6-Digit Authenticator Code" 
                        size="small" 
                        value={twoFaDisableCode} 
                        onChange={(e) => setTwoFaDisableCode(e.target.value)} 
                      />
                      <Button 
                        id="2fa-disable-btn"
                        variant="outlined" 
                        color="error" 
                        onClick={handleDisable2FA}
                        sx={{ fontWeight: 'bold' }}
                      >
                        Disable 2FA
                      </Button>
                    </Box>
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </TabPanel>

      {/* Alert Channels Tab */}
      <TabPanel value={tabValue} index={1}>
        <Grid container spacing={3}>
          {/* Telegram alerts */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.2 }}>
                    <Smartphone size={20} color="#3b82f6" /> Telegram Alerts
                  </Typography>
                  <Typography variant="caption" sx={{ color: tgStatus.configured ? 'success.main' : 'text.secondary', fontWeight: 'bold' }}>
                    {tgStatus.configured ? 'Connected' : 'Not configured'}
                  </Typography>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                  Get instant prediction updates on Telegram. Start chat with{' '}
                  <a href="https://t.me/BullLogicBot" target="_blank" rel="noopener noreferrer" style={{ color: '#8b5cf6', fontWeight: 'bold' }}>
                    @BullLogicBot
                  </a>
                  , send <code>/start</code>, then paste your chat ID below.
                </Typography>
                <Box sx={{ display: 'flex', gap: 1.5 }}>
                  <TextField 
                    id="tg-chat-id"
                    label="Telegram Chat ID" 
                    size="small" 
                    value={tgChatId} 
                    onChange={(e) => setTgChatId(e.target.value)} 
                    fullWidth
                  />
                  <Button 
                    id="tg-connect-btn"
                    variant="contained" 
                    onClick={handleSaveTelegram}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Connect
                  </Button>
                  {tgStatus.configured && (
                    <Button 
                      id="tg-disconnect-btn"
                      variant="outlined" 
                      color="error" 
                      onClick={handleRemoveTelegram}
                      sx={{ fontWeight: 'bold' }}
                    >
                      Remove
                    </Button>
                  )}
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* WhatsApp alerts */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.2 }}>
                    <MessageSquare size={20} color="#10b981" /> WhatsApp Alerts
                  </Typography>
                  <Typography variant="caption" sx={{ color: waStatus.configured ? 'success.main' : 'text.secondary', fontWeight: 'bold' }}>
                    {waStatus.configured ? 'Connected' : 'Not configured'}
                  </Typography>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                  Receive indicators & watchlist alerts on WhatsApp. Enter your number in international format, e.g. <code>+254712345678</code>.
                </Typography>
                <Box sx={{ display: 'flex', gap: 1.5 }}>
                  <TextField 
                    id="wa-phone"
                    label="WhatsApp Phone" 
                    size="small" 
                    value={waPhone} 
                    onChange={(e) => setWaPhone(e.target.value)} 
                    fullWidth
                  />
                  <Button 
                    id="wa-connect-btn"
                    variant="contained" 
                    onClick={handleSaveWhatsapp}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Connect
                  </Button>
                  {waStatus.configured && (
                    <Button 
                      id="wa-disconnect-btn"
                      variant="outlined" 
                      color="error" 
                      onClick={handleRemoveWhatsapp}
                      sx={{ fontWeight: 'bold' }}
                    >
                      Remove
                    </Button>
                  )}
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Discord alerts */}
          <Grid size={12}>
            <Card>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.2 }}>
                    <Globe size={20} color="#5865F2" /> Discord Alerts
                  </Typography>
                  <Typography variant="caption" sx={{ color: discordStatus.configured ? 'success.main' : 'text.secondary', fontWeight: 'bold' }}>
                    {discordStatus.configured ? 'Connected' : 'Not configured'}
                  </Typography>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                  Redirect alerts to your Discord guild channel using a Webhook integration.{' '}
                  <a href="https://support.discord.com/hc/en-us/articles/228383668" target="_blank" rel="noopener noreferrer" style={{ color: '#8b5cf6' }}>
                    Webhook configuration instructions
                  </a>
                </Typography>
                <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
                  <TextField 
                    id="dc-webhook"
                    label="Discord Webhook URL" 
                    size="small" 
                    placeholder="https://discord.com/api/webhooks/..."
                    value={discordWebhookUrl} 
                    onChange={(e) => setDiscordWebhookUrl(e.target.value)} 
                    sx={{ flex: 1, minWidth: 280 }}
                  />
                  <Button 
                    id="dc-connect-btn"
                    variant="contained" 
                    onClick={handleSaveDiscord}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Connect
                  </Button>
                  {discordStatus.configured && (
                    <>
                      <Button 
                        id="dc-test-btn"
                        variant="outlined" 
                        onClick={handleTestDiscord}
                        sx={{ fontWeight: 'bold' }}
                      >
                        Test
                      </Button>
                      <Button 
                        id="dc-disconnect-btn"
                        variant="outlined" 
                        color="error" 
                        onClick={handleRemoveDiscord}
                        sx={{ fontWeight: 'bold' }}
                      >
                        Remove
                      </Button>
                    </>
                  )}
                </Box>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </TabPanel>

      {/* Developers Tab */}
      <TabPanel value={tabValue} index={2}>
        <Grid container spacing={3}>
          {/* API Keys */}
          <Grid size={12}>
            <Card>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  API Keys
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Access prediction endpoints programmatically using Bearer auth.
                  Endpoint format: <code>/api/v1/predict/AAPL?key=YOUR_KEY</code> (Pro feature).
                </Typography>

                <Box sx={{ display: 'flex', gap: 2 }}>
                  <TextField 
                    id="apikey-name"
                    label="Key name (e.g. Server)" 
                    size="small" 
                    value={apiKeyName} 
                    onChange={(e) => setApiKeyName(e.target.value)} 
                  />
                  <Button 
                    id="apikey-create-btn"
                    variant="contained" 
                    color="primary" 
                    onClick={handleCreateApiKey}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Create Key
                  </Button>
                </Box>

                {newlyCreatedKey && (
                  <Box sx={{ p: 2, bgcolor: 'rgba(16,185,129,0.05)', border: '1px solid #10b981', borderRadius: 2 }}>
                    <Typography variant="subtitle2" color="success.main" sx={{ fontWeight: 'bold', mb: 1 }}>
                      API Key generated successfully! Copy it now, it will not be shown again:
                    </Typography>
                    <code style={{ fontSize: '1.1rem', wordBreak: 'break-all', display: 'block', padding: 10, background: 'rgba(0,0,0,0.2)', borderRadius: 4 }}>
                      {newlyCreatedKey}
                    </code>
                  </Box>
                )}

                {loadingKeys ? (
                  <CircularProgress size={24} />
                ) : (
                  <List sx={{ bgcolor: 'rgba(0,0,0,0.1)', borderRadius: 2 }}>
                    {apiKeys.length === 0 ? (
                      <ListItem><ListItemText primary="No API keys registered." /></ListItem>
                    ) : (
                      apiKeys.map((k) => (
                        <ListItem key={k.id} divider>
                          <ListItemText 
                            primary={k.name}
                            secondary={`Preview: ${k.key_preview} · Created: ${k.created_at} · Calls today: ${k.calls_today}`}
                          />
                          <ListItemSecondaryAction>
                            <IconButton 
                              id={`apikey-revoke-${k.id}`}
                              edge="end" 
                              color="error" 
                              onClick={() => handleRevokeApiKey(k.id)}
                            >
                              <Trash2 size={16} />
                            </IconButton>
                          </ListItemSecondaryAction>
                        </ListItem>
                      ))
                    )}
                  </List>
                )}
              </CardContent>
            </Card>
          </Grid>

          {/* Webhooks list/add */}
          <Grid size={12}>
            <Card>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  Custom Webhooks
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Trigger automated HTTP POST requests payload to your own servers on alert/signals occurrences.
                </Typography>

                <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  <TextField 
                    id="wh-name"
                    label="Webhook Name" 
                    size="small" 
                    value={webhookName} 
                    onChange={(e) => setWebhookName(e.target.value)} 
                  />
                  <TextField 
                    id="wh-url"
                    label="Webhook URL" 
                    size="small" 
                    placeholder="https://..."
                    value={webhookUrl} 
                    onChange={(e) => setWebhookUrl(e.target.value)} 
                    sx={{ flex: 1, minWidth: 260 }}
                  />
                  <Button 
                    id="wh-add-btn"
                    variant="contained" 
                    color="primary" 
                    onClick={handleAddWebhook}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Add Webhook
                  </Button>
                </Box>

                {loadingWebhooks ? (
                  <CircularProgress size={24} />
                ) : (
                  <List sx={{ bgcolor: 'rgba(0,0,0,0.1)', borderRadius: 2 }}>
                    {webhooks.length === 0 ? (
                      <ListItem><ListItemText primary="No custom webhooks configured." /></ListItem>
                    ) : (
                      webhooks.map((w) => (
                        <ListItem key={w.id} divider>
                          <ListItemText 
                            primary={w.name}
                            secondary={`URL: ${w.url} · Active: ${w.active ? 'Yes' : 'No'} · Count: ${w.fire_count}`}
                          />
                          <ListItemSecondaryAction sx={{ display: 'flex', gap: 1 }}>
                            <Button 
                              id={`wh-test-${w.id}`}
                              size="small" 
                              variant="outlined" 
                              onClick={() => handleTestWebhook(w.id)}
                            >
                              Test
                            </Button>
                            <IconButton 
                              id={`wh-delete-${w.id}`}
                              edge="end" 
                              color="error" 
                              onClick={() => handleDeleteWebhook(w.id)}
                            >
                              <Trash2 size={16} />
                            </IconButton>
                          </ListItemSecondaryAction>
                        </ListItem>
                      ))
                    )}
                  </List>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </TabPanel>

      {/* Accuracy & Settings Tab */}
      <TabPanel value={tabValue} index={3}>
        <Grid container spacing={3}>
          {/* Prediction Accuracy card */}
          <Grid size={12}>
            <Card>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                    Prediction Accuracy Track Record
                  </Typography>
                  <Button 
                    id="accuracy-refresh-btn"
                    variant="outlined" 
                    size="small" 
                    onClick={loadAccuracy} 
                    startIcon={<RefreshCw size={14} />}
                  >
                    Refresh Stats
                  </Button>
                </Box>

                {loadingAccuracy ? (
                  <CircularProgress size={24} />
                ) : !accuracyStats || accuracyStats.count === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    No prediction accuracy records generated yet. Run some predictions and check back tomorrow.
                  </Typography>
                ) : (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <Grid container spacing={2}>
                      <Grid size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.15)', borderRadius: 2, border: '1px solid rgba(255,255,255,0.03)' }}>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Direction Accuracy</Typography>
                          <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5, color: getAccuracyColor(accuracyStats.direction_accuracy) }}>
                            {accuracyStats.direction_accuracy}%
                          </Typography>
                        </Box>
                      </Grid>

                      <Grid size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.15)', borderRadius: 2, border: '1px solid rgba(255,255,255,0.03)' }}>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Average Price Deviation</Typography>
                          <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5 }}>
                            {accuracyStats.avg_pct_error}%
                          </Typography>
                        </Box>
                      </Grid>

                      <Grid size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.15)', borderRadius: 2, border: '1px solid rgba(255,255,255,0.03)' }}>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Total Checked</Typography>
                          <Typography variant="h5" sx={{ fontWeight: 'bold', mt: 0.5 }}>
                            {accuracyStats.count}
                          </Typography>
                        </Box>
                      </Grid>
                    </Grid>
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>

          {/* Subscription Package & Gift Code Card */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  Redeem Gift Code
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Redeem Pro access key code credentials.
                </Typography>
                <Box sx={{ display: 'flex', gap: 2 }}>
                  <TextField 
                    id="giftcode-input"
                    label="6-Character Gift Code" 
                    size="small" 
                    placeholder="XXXXXX"
                    value={giftCode} 
                    onChange={(e) => setGiftCode(e.target.value)} 
                  />
                  <Button 
                    id="giftcode-redeem-btn"
                    variant="contained" 
                    color="primary" 
                    onClick={handleRedeemGift}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Redeem Code
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Appearance & Daily digest */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  General Preferences
                </Typography>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <TextField 
                    label="Theme Mode"
                    select
                    size="small"
                    value={theme}
                    onChange={(e) => handleUpdateTheme(e.target.value)}
                    fullWidth
                  >
                    <MenuItem value="light">Light Mode</MenuItem>
                    <MenuItem value="dark">Dark Mode</MenuItem>
                    <MenuItem value="system">System Settings</MenuItem>
                  </TextField>

                  <FormControlLabel
                    control={
                      <Switch 
                        checked={usageNotice} 
                        onChange={(e) => handleToggleUsageNotice(e.target.checked)} 
                        color="primary"
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 'medium' }}>Gentle Check-ins</Typography>
                        <Typography variant="caption" color="text.secondary">Show feedback prompt if predictions volume is high</Typography>
                      </Box>
                    }
                  />

                  <Button 
                    id="digest-send-btn"
                    variant="outlined" 
                    color="primary" 
                    onClick={handleSendDigest}
                    disabled={sendingDigest}
                    startIcon={sendingDigest ? <CircularProgress size={16} color="inherit" /> : <Send size={16} />}
                    sx={{ alignSelf: 'flex-start', mt: 1, fontWeight: 'bold' }}
                  >
                    Send Daily Digest Email
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Danger zone / Data tools */}
          <Grid size={12}>
            <Card sx={{ border: '1px solid rgba(255,77,77,0.2)', bgcolor: 'rgba(255,77,77,0.01)' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'error.main' }}>
                  Danger Zone
                </Typography>

                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
                  <Box>
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Export Account Data</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      Download all details, configurations, and records stashed.
                    </Typography>
                  </Box>
                  <Button 
                    id="data-export-btn"
                    component="a" 
                    href="/api/account/export"
                    variant="outlined" 
                    color="inherit" 
                    startIcon={<Download size={16} />}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Export my data (JSON)
                  </Button>
                </Box>

                <Divider sx={{ borderColor: 'rgba(255,77,77,0.1)' }} />

                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
                  <Box>
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: 'error.main' }}>Permanently Delete Account</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      This action will wipe all credentials, settings, alerts and predictions histories.
                    </Typography>
                  </Box>
                  <Button 
                    id="account-delete-btn"
                    variant="contained" 
                    color="error" 
                    onClick={handleDeleteAccount}
                    sx={{ fontWeight: 'bold' }}
                  >
                    Delete Account
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </TabPanel>
    </Box>
  );
};

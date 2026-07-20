import React, { useState, useEffect } from 'react';
import { BookOpen, ExternalLink } from 'lucide-react';
import { Box, Typography, Card, CardContent, Grid, CircularProgress } from '@mui/material';
import { apiFetch } from '../utils/api';

interface ResourceLink {
  title: string;
  url: string;
  description: string | null;
  icon: string | null;
}

interface ResourceCategory {
  name: string;
  links: ResourceLink[];
}

export const ResourcesDashboard: React.FC = () => {
  const [categories, setCategories] = useState<ResourceCategory[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchResources = async () => {
      try {
        const response = await apiFetch('/api/resources');
        if (response.ok && response.categories) {
          setCategories(response.categories);
        }
      } catch (err) {
        console.error('Failed to load resources:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchResources();
  }, []);

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* Header */}
      <Box>
        <Typography variant="h2" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontSize: '1.5rem', color: 'text.primary', fontWeight: 'bold' }}>
          <BookOpen color="#8b5cf6" />
          Resources Hub
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Curated guides, links, and documents for trading, market information, and staying safe.
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          Disclaimer: External sites are not operated by BullLogic. We are not responsible for their content.
        </Typography>
      </Box>

      {loading ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 12, gap: 2 }}>
          <CircularProgress color="primary" />
          <Typography color="text.secondary">Loading resources links...</Typography>
        </Box>
      ) : categories.length === 0 ? (
        <Card sx={{ display: 'flex', justifyContent: 'center', py: 8, border: '1px dashed rgba(255,255,255,0.05)' }}>
          <Typography color="text.secondary">No resources published yet. Check back soon.</Typography>
        </Card>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {categories.map((cat, idx) => (
            <Box key={idx}>
              <Typography variant="subtitle2" sx={{ textTransform: 'uppercase', color: 'primary.main', fontWeight: 'bold', mb: 2, letterSpacing: 0.5 }}>
                {cat.name}
              </Typography>
              <Grid container spacing={2}>
                {cat.links.map((link, lIdx) => {
                  const isExternal = link.url.startsWith('http');
                  return (
                    <Grid size={{ xs: 12, sm: 6, md: 4 }} key={lIdx}>
                      <Card 
                        component="a" 
                        href={link.url}
                        target={isExternal ? '_blank' : '_self'}
                        rel={isExternal ? 'noopener noreferrer' : undefined}
                        sx={{ 
                          display: 'flex',
                          height: '100%',
                          textDecoration: 'none',
                          border: '1px solid rgba(255,255,255,0.05)',
                          transition: 'all 0.2s',
                          cursor: 'pointer',
                          '&:hover': {
                            borderColor: 'primary.main',
                            transform: 'translateY(-2px)',
                          }
                        }}
                      >
                        <CardContent sx={{ p: 3, display: 'flex', gap: 2, alignItems: 'flex-start', width: '100%' }}>
                          <span style={{ fontSize: '1.5rem', lineHeight: 1 }}>
                            {link.icon || '🔗'}
                          </span>
                          <Box sx={{ flex: 1 }}>
                            <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'flex', alignItems: 'center', gap: 1 }}>
                              {link.title}
                              {isExternal && <ExternalLink size={12} color="#a0a5b1" />}
                            </Typography>
                            {link.description && (
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.8, lineHeight: 1.4 }}>
                                {link.description}
                              </Typography>
                            )}
                          </Box>
                        </CardContent>
                      </Card>
                    </Grid>
                  );
                })}
              </Grid>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
};

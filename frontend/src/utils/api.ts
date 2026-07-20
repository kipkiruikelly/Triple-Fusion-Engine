import toast from 'react-hot-toast';

/**
 * A wrapper around fetch that automatically handles:
 * 1. JSON stringifying for body payload
 * 2. CSRF Token injection
 * 3. 401 Unauthorized interception
 * 4. General network error toasts
 */
interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  body?: any;
}

export async function apiFetch(url: string, options: ApiFetchOptions = {}): Promise<any> {
  const headers = new Headers(options.headers || {});
  
  // Try to grab csrf from localStorage where we will stash it
  const csrfToken = localStorage.getItem('csrf_token');
  if (csrfToken && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(options.method?.toUpperCase() || '')) {
    headers.set('X-CSRF-Token', csrfToken);
    headers.set('X-CSRFToken', csrfToken);
  }

  // Auto-set Content-Type for JSON if body is an object and not FormData
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    options.body = JSON.stringify(options.body);
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
  }

  const fetchOptions: RequestInit = {
    ...options,
    headers,
    credentials: 'include',  // Always send session cookies
  };

  try {
    const response = await fetch(url, fetchOptions);

    if (response.status === 401) {
      // Intercept Unauthorized
      localStorage.removeItem('csrf_token'); // Clear token
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
      return { ok: false, error: 'Session expired. Please log in again.' };
    }

    if (response.status === 403) {
       toast.error('Permission Denied / CSRF Token Invalid');
    }

    // Try parsing json
    try {
      const data = await response.json();
      return data;
    } catch (err) {
      // Not JSON
      if (!response.ok) {
         toast.error(`Request failed: ${response.statusText}`);
      }
      return { ok: response.ok, status: response.status };
    }
  } catch (err) {
    // Network error
    toast.error('Network error. Please check your connection.');
    return { ok: false, error: 'Network error' };
  }
}

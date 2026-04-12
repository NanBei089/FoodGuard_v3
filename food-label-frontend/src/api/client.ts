import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@/types/api';

let onForceLogout: (() => void) | null = null;
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

export function setForceLogoutHandler(handler: (() => void) | null) {
  onForceLogout = handler;
}

export function triggerForceLogout() {
  if (onForceLogout) {
    onForceLogout();
  }
}

export function getApiBaseUrl() {
  return API_BASE_URL;
}

function persistAuthTokens(tokens: { access_token: string; refresh_token: string }) {
  localStorage.setItem('access_token', tokens.access_token);
  localStorage.setItem('refresh_token', tokens.refresh_token);
  apiClient.defaults.headers.common['Authorization'] = `Bearer ${tokens.access_token}`;
}

export async function refreshAuthTokens(): Promise<string | null> {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    triggerForceLogout();
    return null;
  }

  try {
    const res = await axios.post(`${API_BASE_URL}/auth/refresh`, {
      refresh_token: refreshToken,
    });

    if (res.data.code === 0) {
      persistAuthTokens(res.data.data);
      return res.data.data.access_token;
    }
  } catch (refreshError) {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    triggerForceLogout();
    throw refreshError;
  }

  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  triggerForceLogout();
  return null;
}

// Create axios instance with base URL
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for API calls
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for API calls
apiClient.interceptors.response.use(
  (response) => {
    return response.data;
  },
  async (error) => {
    const originalRequest = error.config;
    
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        const nextAccessToken = await refreshAuthTokens();
        if (nextAccessToken) {
          originalRequest.headers.Authorization = `Bearer ${nextAccessToken}`;
          return apiClient(originalRequest);
        }
      } catch (refreshError) {
        return Promise.reject(refreshError);
      }
    }
    
    return Promise.reject(error);
  }
);

export function apiGet<T>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return apiClient.get(url, config) as Promise<ApiResponse<T>>;
}

export function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<T>> {
  return apiClient.post(url, data, config) as Promise<ApiResponse<T>>;
}

export function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<T>> {
  return apiClient.put(url, data, config) as Promise<ApiResponse<T>>;
}

export function apiPatch<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<T>> {
  return apiClient.patch(url, data, config) as Promise<ApiResponse<T>>;
}

export function apiDelete<T>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return apiClient.delete(url, config) as Promise<ApiResponse<T>>;
}

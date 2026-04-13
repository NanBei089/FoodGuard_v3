import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@/types/api';

let onForceLogout: (() => void) | null = null;
let refreshPromise: Promise<string | null> | null = null;
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';
const REFRESH_TIMEOUT_MS = 12000;

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

function isApiResponseEnvelope(value: unknown): value is ApiResponse<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    'code' in value &&
    typeof (value as { code?: unknown }).code === 'number' &&
    'message' in value &&
    typeof (value as { message?: unknown }).message === 'string' &&
    'data' in value
  );
}

function persistAuthTokens(tokens: { access_token: string; refresh_token: string }) {
  localStorage.setItem('access_token', tokens.access_token);
  localStorage.setItem('refresh_token', tokens.refresh_token);
  apiClient.defaults.headers.common['Authorization'] = `Bearer ${tokens.access_token}`;
}

function clearAuthTokens() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  delete apiClient.defaults.headers.common['Authorization'];
}

export async function refreshAuthTokens(): Promise<string | null> {
  if (refreshPromise) {
    return refreshPromise;
  }

  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) {
    clearAuthTokens();
    triggerForceLogout();
    return null;
  }

  refreshPromise = (async () => {
    try {
      const res = await axios.post(
        `${API_BASE_URL}/auth/refresh`,
        {
          refresh_token: refreshToken,
        },
        {
          timeout: REFRESH_TIMEOUT_MS,
        },
      );

      if (res.data.code === 0) {
        persistAuthTokens(res.data.data);
        return res.data.data.access_token;
      }
    } catch (refreshError) {
      clearAuthTokens();
      triggerForceLogout();
      throw refreshError;
    } finally {
      refreshPromise = null;
    }

    clearAuthTokens();
    triggerForceLogout();
    return null;
  })();

  return refreshPromise;
}

// Create axios instance with base URL
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
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
    if (isApiResponseEnvelope(response.data)) {
      return response;
    }

    const method = response.config?.method?.toUpperCase();
    const url = response.config?.url;
    throw new Error(
      method && url
        ? `Unexpected API response format from ${method} ${url}`
        : 'Unexpected API response format',
    );
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
  return apiClient
    .get<ApiResponse<T>>(url, config)
    .then((response) => response.data);
}

export function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<T>> {
  return apiClient
    .post<ApiResponse<T>>(url, data, config)
    .then((response) => response.data);
}

export function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<T>> {
  return apiClient
    .put<ApiResponse<T>>(url, data, config)
    .then((response) => response.data);
}

export function apiPatch<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<T>> {
  return apiClient
    .patch<ApiResponse<T>>(url, data, config)
    .then((response) => response.data);
}

export function apiDelete<T>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return apiClient
    .delete<ApiResponse<T>>(url, config)
    .then((response) => response.data);
}

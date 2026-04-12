import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@/types/api';

let onForceLogout: (() => void) | null = null;

export function setForceLogoutHandler(handler: (() => void) | null) {
  onForceLogout = handler;
}

// Create axios instance with base URL
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
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
      const refreshToken = localStorage.getItem('refresh_token');
      
      if (refreshToken) {
        try {
          const res = await axios.post(`${import.meta.env.VITE_API_URL || '/api/v1'}/auth/refresh`, {
            refresh_token: refreshToken
          });
          
          if (res.data.code === 0) {
            localStorage.setItem('access_token', res.data.data.access_token);
            localStorage.setItem('refresh_token', res.data.data.refresh_token);
            apiClient.defaults.headers.common['Authorization'] = `Bearer ${res.data.data.access_token}`;
            return apiClient(originalRequest);
          }
        } catch (refreshError) {
          // If refresh fails, clear tokens and redirect to login
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          if (onForceLogout) {
            onForceLogout();
          }
          return Promise.reject(refreshError);
        }
      } else {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        if (onForceLogout) {
          onForceLogout();
        }
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

import axios from 'axios'

export const AUTH_TOKEN_STORAGE_KEY = 'csslab.authToken'

export function getAuthToken(): string {
  try {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setAuthToken(token: string) {
  const value = (token || '').trim()
  try {
    if (!value) {
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
    } else {
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, value)
    }
  } catch {
    // ignore storage errors (private mode, disabled storage, etc.)
  }
}

export function clearAuthToken() {
  setAuthToken('')
}

const http = axios.create()

http.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) {
    config.headers = config.headers ?? {}
    ;(config.headers as any).Authorization = `Bearer ${token}`
  }
  return config
})

export default http


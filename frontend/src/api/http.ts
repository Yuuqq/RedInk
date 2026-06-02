import axios from 'axios'

export const AUTH_TOKEN_STORAGE_KEY = 'csslab.authToken'

export function getAuthToken(): string {
  try {
    const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || ''
    syncImageAuthCookie(token)
    return token
  } catch {
    return ''
  }
}

export function setAuthToken(token: string) {
  const value = (token || '').trim()
  syncImageAuthCookie(value)
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

function syncImageAuthCookie(token: string) {
  if (typeof document === 'undefined') return

  try {
    const secure = window.location.protocol === 'https:' ? '; Secure' : ''
    if (!token) {
      document.cookie = `redink_auth_token=; Path=/api/images; SameSite=Lax; Max-Age=0${secure}`
      return
    }

    document.cookie = `redink_auth_token=${encodeURIComponent(token)}; Path=/api/images; SameSite=Lax; Max-Age=2592000${secure}`
  } catch {
    // Ignore cookie write failures; regular API calls still use Authorization.
  }
}

try {
  syncImageAuthCookie(localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || '')
} catch {
  // Ignore storage errors during module initialization.
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


import axios from 'axios'

export const AUTH_TOKEN_STORAGE_KEY = 'csslab.authToken'

// 清除旧的非 HttpOnly cookie
if (typeof document !== 'undefined') {
  try {
    const cookies = document.cookie.split(';')
    for (const cookie of cookies) {
      if (cookie.trim().startsWith('redink_auth_token=')) {
        document.cookie = 'redink_auth_token=; Path=/api/images; Max-Age=0'
        document.cookie = 'redink_auth_token=; Path=/; Max-Age=0'
      }
    }
  } catch (e) {}
}

export function getAuthToken(): string {
  try {
    const hasToken = localStorage.getItem('csslab.hasAuthToken')
    if (hasToken) return '********'

    // 迁移旧的 token
    const oldToken = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
    if (oldToken) {
      setAuthToken(oldToken)
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
      return '********'
    }
    return ''
  } catch {
    return ''
  }
}

export function setAuthToken(token: string) {
  const value = (token || '').trim()
  if (!value) {
    localStorage.removeItem('csslab.hasAuthToken')
    axios.delete('/api/auth/session').catch(e => console.error('Failed to clear auth session', e))
  } else if (value !== '********') {
    axios.post('/api/auth/session', { token: value }).catch(e => console.error('Failed to set auth session', e))
    localStorage.setItem('csslab.hasAuthToken', '1')
  }
}

export function clearAuthToken() {
  setAuthToken('')
}

const http = axios.create()

http.interceptors.request.use((config) => {
  config.withCredentials = true
  return config
})

export default http

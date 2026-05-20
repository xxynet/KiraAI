import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'
import type { TokenLoginRequest } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('jwt_token'))

  const isAuthenticated = computed(() => !!token.value)

  async function login(accessToken: string) {
    const data: TokenLoginRequest = { access_token: accessToken }
    const response = await authApi.login(data)
    token.value = response.data.access_token
    localStorage.setItem('jwt_token', response.data.access_token)
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      token.value = null
      localStorage.removeItem('jwt_token')
    }
  }

  function clearAuth() {
    token.value = null
    localStorage.removeItem('jwt_token')
  }

  return {
    token,
    isAuthenticated,
    login,
    logout,
    clearAuth,
  }
})

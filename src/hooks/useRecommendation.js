import { useState } from 'react'
import { requestRecommendation } from '../api/recommendationApi'

export function useRecommendation() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')

  const request = async (payload) => {
    setStatus('loading')
    setError('')
    try {
      const result = await requestRecommendation(payload)
      setStatus('success')
      return result
    } catch (requestError) {
      setStatus('error')
      setError(requestError.message)
      return null
    }
  }

  return { status, error, request }
}

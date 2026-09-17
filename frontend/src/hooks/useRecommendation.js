import { useState } from 'react'
import { requestRecommendation } from '../api/recommendationApi'

export function useRecommendation() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')

  const request = async (payload, options) => {
    setStatus('loading')
    setError('')
    try {
      const result = await requestRecommendation(payload, options)
      setStatus('success')
      return result
    } catch (requestError) {
      if (requestError.name === 'AbortError') {
        setStatus('idle')
        return null
      }
      setStatus('error')
      setError(requestError.message)
      return null
    }
  }

  return { status, error, request }
}

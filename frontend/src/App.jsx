import WelcomePage from './pages/WelcomePage'
import HomePage from './pages/HomePage'
import AnalysisLoading from './components/recommendation/AnalysisLoading'
import { useRecommendation } from './hooks/useRecommendation'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { removeSession, writeSession } from './utils/sessionStore'
import { getMe, getPersonalizationProfile, getPreferences } from './api/accountApi'

const RecommendationPage = lazy(() => import('./pages/RecommendationPage'))

function App() {
  // 새로고침은 새 세션으로 시작한다. 저장된 자동추천 화면을 다시 마운트하면
  // 실제 경로 검증 요청이 재실행되므로 결과 화면을 자동 복원하지 않는다.
  const [result, setResult] = useState(null)
  const [view, setView] = useState('welcome')
  const requestId = useRef(0)
  const recommendationController = useRef(null)
  const { request, error } = useRecommendation()
  const [account, setAccount] = useState({ token: localStorage.getItem('koala-token'), user: null, preferences: null })
  const [accountRequestId, setAccountRequestId] = useState(0)
  const returnToResultAfterAccount = useRef(false)

  // 결과 화면에서 로그인이 필요해도 작성 중인 코스를 폐기하지 않는다.
  const handleAccountChange = (nextAccount) => {
    setAccount(nextAccount)
    if (returnToResultAfterAccount.current && result) {
      returnToResultAfterAccount.current = false
      setView('result')
    }
  }

  const closeAccountFromResult = () => {
    if (!returnToResultAfterAccount.current || !result) return
    returnToResultAfterAccount.current = false
    setView('result')
  }

  useEffect(() => {
    let secondFrame = 0
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        console.info(`[PERFORMANCE] first-screen-display=${Math.round(performance.now())}ms status=success`)
      })
    })
    return () => {
      cancelAnimationFrame(firstFrame)
      cancelAnimationFrame(secondFrame)
    }
  }, [])

  useEffect(() => {
    const token = localStorage.getItem('koala-token')
    if (!token) return
    Promise.all([getMe(token), getPreferences(token), getPersonalizationProfile(token)])
      .then(([user, preferences, personalization]) => setAccount({ token, user, preferences, personalization }))
      .catch((restoreError) => {
        // 네트워크 단절이나 서버 점검은 로그아웃 사유가 아니다. 서버가 토큰을
        // 명시적으로 거부한 경우에만 저장된 로그인 정보를 제거한다.
        if (restoreError?.status === 401) {
          localStorage.removeItem('koala-token')
          setAccount({ token: null, user: null, preferences: null, personalization: null })
        }
      })
  }, [])

  const handleRecommendation = async (payload) => {
    recommendationController.current?.abort()
    const controller = new AbortController()
    recommendationController.current = controller
    const currentRequestId = ++requestId.current
    // 새 추천은 이전 지역·장소·코스와 독립적이다. 이전 응답이 화면에 남아
    // 고척돔 같은 과거 결과가 이어 보이지 않게 먼저 비운다.
    setResult(null)
    removeSession('koala-result')
    setView('loading')
    // 인증 토큰은 서버가 DB의 명시적·행동 기반 취향을 불러올 때만 사용한다.
    const response = await request({ ...payload, token: account.token }, { signal: controller.signal })
    if (currentRequestId !== requestId.current) return
    recommendationController.current = null
    if (response) {
      const nextResult = payload.autoCourse
        ? { ...response, _client_mode: 'auto-course', _client_selected_duration_minutes: payload.autoCourseDurationMinutes, _client_user_message: payload.message }
        : { ...response, _client_user_message: payload.message, _client_adventure_mode: payload.adventureMode ?? null }
      setResult(nextResult)
      writeSession('koala-result', nextResult)
      setView('result')
    } else {
      setView('home')
    }
  }

  const cancelRecommendation = () => {
    requestId.current += 1
    recommendationController.current?.abort()
    recommendationController.current = null
    setResult(null)
    removeSession('koala-result')
    setView('home')
  }

  const openSavedCourse = (savedCourse) => {
    const savedResponse = savedCourse?.course_data?.recommendation_response
    if (!savedResponse) return false
    const restored = { ...savedResponse, _client_saved_course: savedCourse }
    setResult(restored)
    writeSession('koala-result', restored)
    setView('result')
    return true
  }

  return (
    <div className={view !== 'welcome' ? 'app-shell is-home-open' : 'app-shell'}>
      <WelcomePage onStart={() => setView('home')} />
      <HomePage isOpen={view === 'home'} onRecommend={handleRecommendation} onOpenSavedCourse={openSavedCourse} error={error} account={account} onAccountChange={handleAccountChange} accountRequestId={accountRequestId} onAccountClose={closeAccountFromResult} />
      {view === 'loading' && <AnalysisLoading onEdit={cancelRecommendation} onCancel={cancelRecommendation} />}
      {result && (view === 'result' || returnToResultAfterAccount.current) && <Suspense fallback={<AnalysisLoading onEdit={() => setView('home')} onCancel={() => setView('home')} />}><RecommendationPage response={result} onBack={() => { setResult(null); removeSession('koala-result'); setView('home') }} account={account} onOpenAccount={() => { returnToResultAfterAccount.current = true; setView('home'); setAccountRequestId((current) => current + 1) }} /></Suspense>}
    </div>
  )
}

export default App

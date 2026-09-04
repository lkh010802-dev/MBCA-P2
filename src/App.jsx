import WelcomePage from './pages/WelcomePage'
import HomePage from './pages/HomePage'
import AnalysisLoading from './components/recommendation/AnalysisLoading'
import RecommendationPage from './pages/RecommendationPage'
import { useRecommendation } from './hooks/useRecommendation'
import { useRef, useState } from 'react'

function App() {
  const [view, setView] = useState('welcome')
  const [result, setResult] = useState(null)
  const requestId = useRef(0)
  const { request, error } = useRecommendation()

  const handleRecommendation = async (payload) => {
    const currentRequestId = ++requestId.current
    setView('loading')
    const response = await request(payload)
    if (currentRequestId !== requestId.current) return
    if (response) {
      setResult(response)
      setView('result')
    } else {
      setView('home')
    }
  }

  return (
    <div className={view !== 'welcome' ? 'app-shell is-home-open' : 'app-shell'}>
      <WelcomePage onStart={() => setView('home')} />
      <HomePage isOpen={view === 'home'} onRecommend={handleRecommendation} error={error} />
      {view === 'loading' && <AnalysisLoading onEdit={() => { requestId.current += 1; setView('home') }} onCancel={() => { requestId.current += 1; setView('home') }} />}
      {view === 'result' && <RecommendationPage response={result} onBack={() => setView('home')} />}
    </div>
  )
}

export default App

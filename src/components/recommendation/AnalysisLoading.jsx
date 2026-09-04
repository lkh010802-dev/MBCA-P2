import { useEffect, useState } from 'react'
import koalaThinking from '../../assets/images/koala-thinking.png'

const STEPS = ['현재 위치 확인', '이동 가능한 지역 계산', '주변 장소 탐색', '혼잡도와 활동 적합도 분석']

function AnalysisLoading({ onEdit, onCancel }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const activeStep = Math.min(STEPS.length - 1, Math.floor(elapsed / 3))
  const progress = Math.min(92, 14 + elapsed * 6)
  const statusMessage = STEPS[activeStep] === '주변 장소 탐색' ? '주변 장소를 비교하고 있어요' : `${STEPS[activeStep]} 중이에요`
  return (
    <main className="analysis-page">
      <img className="analysis-koala" src={koalaThinking} alt="지도를 보며 코스를 생각하는 코알라" />
      <p className="analysis-brand">코알라가 코스를 찾고 있어요</p>
      <h1>잠깐만 기다려주세요</h1>
      <p className="analysis-status">{statusMessage} · {elapsed}초 경과</p>
      <div className="analysis-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>
      <div className="analysis-steps">
        {STEPS.map((step, index) => <span className={index < activeStep ? 'is-done' : index === activeStep ? 'is-active' : ''} key={step}><i aria-hidden="true">{index < activeStep ? '✓' : index === activeStep ? '·' : ''}</i>{step}</span>)}
      </div>
      <div className="analysis-actions"><button type="button" onClick={onEdit}>입력 수정하기</button><button type="button" onClick={onCancel}>취소</button></div>
    </main>
  )
}

export default AnalysisLoading

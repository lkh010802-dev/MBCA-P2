import { useState } from 'react'
import { useCurrentLocation } from '../hooks/useCurrentLocation'
import koalaPeeking from '../assets/images/koala-peeking.png'

function HomePage({ isOpen, onRecommend, error }) {
  const [message, setMessage] = useState('')
  const { location, address, status, requestLocation } = useCurrentLocation()

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!message.trim()) return
    onRecommend({ message, location })
  }

  const locationText = status === 'success'
    ? '현재 위치를 사용하고 있어요'
    : status === 'loading' ? '현재 위치를 확인하는 중이에요'
      : status === 'denied' ? '위치 없이도 추천받을 수 있어요'
        : status === 'unsupported' ? '이 기기에서는 위치를 지원하지 않아요'
          : '현재 위치를 알려주시면 더 정확해요'

  return (
    <main className={isOpen ? 'home-page home-page--sheet is-open' : 'home-page home-page--sheet'}>
      <img className="home-peeking-koala" src={koalaPeeking} alt="" />
      <header className="home-header">
        <p className="home-brand">코알라</p>
      </header>
      <section className="home-intro">
        <p className="home-eyebrow">오늘의 빈 시간을 채워볼까요?</p>
        <h1>오늘의 빈 시간을<br />채워볼까요?</h1>
      </section>
      <button className={`location-card location-card--${status}`} type="button" onClick={requestLocation}>
        <span className="location-icon">⌖</span>
        <span><strong>{locationText}</strong><small>{status === 'success' ? (address?.road_address || address?.jibun_address || '주소를 확인하는 중이에요') : '눌러서 현재 위치 확인하기'}</small></span>
        <span className="location-action">{status === 'loading' ? '…' : '›'}</span>
      </button>
      <form className="recommendation-form" onSubmit={handleSubmit}>
        <label htmlFor="recommendation-message">어떤 시간을 보내고 싶으세요?</label>
        <textarea id="recommendation-message" value={message} onChange={(event) => setMessage(event.target.value)} spellCheck={false} placeholder={'예) 지금부터 3시간 정도 시간 있고\n8시에 잠실 가야 해. 카페나 전시 보고 싶어.'} />
        <section className="recommendation-guide" aria-label="코알라 추천 기준">
          <div className="guide-heading">
            <span className="guide-bubble">코알라가 살펴볼게요</span>
            <small>한 문장에 담아주세요</small>
          </div>
          <div className="guide-items">
            <span><b aria-hidden="true">📍</b>현재 위치</span>
            <span><b aria-hidden="true">⏱</b>남은 시간</span>
            <span><b aria-hidden="true">🗓</b>다음 일정</span>
            <span><b aria-hidden="true">✨</b>하고 싶은 활동</span>
          </div>
        </section>
        {error && <p className="recommendation-error">{error}</p>}
        <button className="recommendation-cta" type="submit" disabled={!message.trim()}>추천받기 <span>→</span></button>
      </form>
    </main>
  )
}

export default HomePage

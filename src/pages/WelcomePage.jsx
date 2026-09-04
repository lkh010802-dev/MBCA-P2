import koalaMascot from '../assets/images/koala-mascot.png'

function WelcomePage({ onStart }) {
  return (
    <main className="welcome-page">
      <section className="welcome-content" aria-labelledby="welcome-title">
        <p className="welcome-kicker">남은 시간을 위한 가장 좋은 선택</p>
        <h1 id="welcome-title" className="welcome-title">
          <span className="title-point">코</span><span className="title-rest">스를</span><br />
          <span className="title-point">알</span><span className="title-rest">려주는</span><br />
          <span className="title-point">라</span><span className="title-rest">인업</span>
        </h1>
        <p className="welcome-description">지금 가기 좋은 곳,<br />AI가 코스로 추천해드려요</p>
      </section>
      <div className="welcome-visual" aria-hidden="true">
        <div className="welcome-cloud welcome-cloud--left" />
        <div className="welcome-cloud welcome-cloud--right" />
        <div className="welcome-city" />
        <img className="welcome-mascot" src={koalaMascot} alt="" />
      </div>
      <button className="welcome-cta" type="button" onClick={onStart}>시작하기</button>
    </main>
  )
}

export default WelcomePage

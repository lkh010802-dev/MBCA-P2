import { useEffect, useRef } from "react";

const ITEM_HEIGHT = 48;

/** Mouse, wheel and touch friendly duration selector. */
export default function TimeWheel({ label, values, value, onChange, suffix }) {
  const wheelRef = useRef(null);
  const frameRef = useRef(null);
  const wheelLockRef = useRef(false);
  const wheelUnlockTimerRef = useRef(null);
  const dragRef = useRef({ active: false, moved: false, startY: 0, startScrollTop: 0 });

  useEffect(() => {
    const index = Math.max(0, values.indexOf(value));
    if (wheelRef.current) wheelRef.current.scrollTop = index * ITEM_HEIGHT;
  }, [value, values]);

  useEffect(
    () => () => {
      cancelAnimationFrame(frameRef.current);
      if (wheelUnlockTimerRef.current)
        clearTimeout(wheelUnlockTimerRef.current);
    },
    [],
  );

  const selectVisibleValue = () => {
    cancelAnimationFrame(frameRef.current);
    frameRef.current = requestAnimationFrame(() => {
      const index = Math.max(0, Math.min(
        values.length - 1,
        Math.round((wheelRef.current?.scrollTop ?? 0) / ITEM_HEIGHT),
      ));
      if (values[index] !== value) onChange(values[index]);
    });
  };

  const handleWheel = (event) => {
    event.preventDefault();
    // 고해상도 마우스·터치패드는 한 번의 제스처에 wheel 이벤트를 여러 번 보낸다.
    // 짧게 입력을 잠가 사용자 동작 한 번당 정확히 한 칸만 이동시킨다.
    if (wheelLockRef.current || Math.abs(event.deltaY) < 2) return;
    const currentIndex = Math.max(0, values.indexOf(value));
    const nextIndex = Math.max(0, Math.min(
      values.length - 1,
      currentIndex + (event.deltaY > 0 ? 1 : -1),
    ));
    if (nextIndex === currentIndex) return;
    wheelLockRef.current = true;
    onChange(values[nextIndex]);
    wheelRef.current?.scrollTo({
      top: nextIndex * ITEM_HEIGHT,
      behavior: "smooth",
    });
    wheelUnlockTimerRef.current = setTimeout(() => {
      wheelLockRef.current = false;
    }, 220);
  };

  return (
    <div className="time-wheel-group">
      <small>{label}</small>
      <div className="time-wheel-frame">
        <div className="time-wheel-highlight" />
        <div
          className="time-wheel"
          ref={wheelRef}
          role="listbox"
          aria-label={label}
          onScroll={selectVisibleValue}
          onWheel={handleWheel}
          onPointerDown={(event) => {
            if (event.pointerType !== "mouse" || event.button !== 0) return;
            dragRef.current = {
              active: true,
              moved: false,
              startY: event.clientY,
              startScrollTop: event.currentTarget.scrollTop,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            event.currentTarget.classList.add("is-dragging");
          }}
          onPointerMove={(event) => {
            if (!dragRef.current.active) return;
            const distance = event.clientY - dragRef.current.startY;
            if (Math.abs(distance) > 3) dragRef.current.moved = true;
            event.currentTarget.scrollTop = dragRef.current.startScrollTop - distance;
          }}
          onPointerUp={(event) => {
            if (!dragRef.current.active) return;
            dragRef.current.active = false;
            event.currentTarget.classList.remove("is-dragging");
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
            selectVisibleValue();
          }}
        >
          {values.map((item) => (
            <button
              type="button"
              role="option"
              aria-selected={item === value}
              className={item === value ? "is-selected" : ""}
              key={item}
              onClick={() => {
                if (dragRef.current.moved) {
                  dragRef.current.moved = false;
                  return;
                }
                const currentIndex = Math.max(0, values.indexOf(value));
                const clickedIndex = values.indexOf(item);
                // 보이는 위·아래 숫자를 클릭하면 한 칸씩 이동하고 중앙에 정렬한다.
                const nextIndex = Math.max(
                  0,
                  Math.min(
                    values.length - 1,
                    currentIndex + Math.sign(clickedIndex - currentIndex),
                  ),
                );
                onChange(values[nextIndex]);
                wheelRef.current?.scrollTo({
                  top: nextIndex * ITEM_HEIGHT,
                  behavior: "smooth",
                });
              }}
            >
              {String(item).padStart(2, "0")}<span>{suffix}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

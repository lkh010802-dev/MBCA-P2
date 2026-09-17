import { useEffect, useRef } from "react";

const ITEM_HEIGHT = 44;

/** Accessible compact wheel used inside the course-time dialog. */
export default function TimeWheelColumn({ label, options, value, onChange }) {
  const wheelRef = useRef(null);
  const scrollTimerRef = useRef(null);
  const wheelLockRef = useRef(false);
  const dragRef = useRef({ active: false, moved: false, startY: 0, startScrollTop: 0 });

  useEffect(() => {
    const selectedIndex = options.indexOf(value);
    if (!wheelRef.current || selectedIndex < 0) return;
    wheelRef.current.scrollTo({ top: selectedIndex * ITEM_HEIGHT, behavior: "smooth" });
  }, [options, value]);

  useEffect(() => () => {
    if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current);
    wheelLockRef.current = false;
  }, []);

  const commitScrollValue = (element) => {
    if (dragRef.current.active) return;
    const nextIndex = Math.max(0, Math.min(
      options.length - 1,
      Math.round(element.scrollTop / ITEM_HEIGHT),
    ));
    const nextValue = options[nextIndex];
    element.scrollTo({ top: nextIndex * ITEM_HEIGHT, behavior: "smooth" });
    if (nextValue !== value) onChange(nextValue);
  };

  return (
    <div className="time-wheel-column">
      <span>{label}</span>
      <div
        ref={wheelRef}
        className="time-wheel-scroll"
        role="listbox"
        aria-label={label}
        aria-activedescendant={`time-wheel-${label}-${value}`}
        onScroll={(event) => {
          if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current);
          const element = event.currentTarget;
          scrollTimerRef.current = setTimeout(() => commitScrollValue(element), 90);
        }}
        onWheel={(event) => {
          event.preventDefault();
          if (wheelLockRef.current || Math.abs(event.deltaY) < 2) return;
          const currentIndex = options.indexOf(value);
          const nextIndex = Math.max(0, Math.min(
            options.length - 1,
            currentIndex + (event.deltaY > 0 ? 1 : -1),
          ));
          if (nextIndex === currentIndex) return;
          wheelLockRef.current = true;
          onChange(options[nextIndex]);
          setTimeout(() => { wheelLockRef.current = false; }, 110);
        }}
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
          commitScrollValue(event.currentTarget);
        }}
        onPointerCancel={(event) => {
          dragRef.current.active = false;
          dragRef.current.moved = false;
          event.currentTarget.classList.remove("is-dragging");
        }}
      >
        <i aria-hidden="true" />
        {options.map((option) => (
          <button
            id={`time-wheel-${label}-${option}`}
            key={option}
            type="button"
            role="option"
            aria-selected={option === value}
            className={option === value ? "is-selected" : ""}
            onClick={(event) => {
              if (dragRef.current.moved) {
                dragRef.current.moved = false;
                return;
              }
              onChange(option);
              event.currentTarget.scrollIntoView({ block: "center", behavior: "smooth" });
            }}
          >
            {String(option).padStart(2, "0")}
          </button>
        ))}
        <i aria-hidden="true" />
      </div>
    </div>
  );
}

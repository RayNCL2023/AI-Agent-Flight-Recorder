/** Typewriter reveal for freshly streamed text; renders instantly otherwise. */

import { useEffect, useRef, useState } from "react";

export function Typewriter({
  text,
  animate,
  speed = 3,
}: {
  text: string;
  animate: boolean;
  /** characters per frame */
  speed?: number;
}) {
  const [count, setCount] = useState(animate ? 0 : text.length);
  const raf = useRef<number>(0);

  useEffect(() => {
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setCount(text.length);
      return;
    }
    setCount(0);
    const tick = () => {
      setCount((c) => {
        if (c >= text.length) return c;
        raf.current = requestAnimationFrame(tick);
        return c + speed;
      });
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [text, animate, speed]);

  const done = count >= text.length;
  return (
    <span className={done ? undefined : "caret"}>
      {text.slice(0, Math.min(count, text.length))}
    </span>
  );
}

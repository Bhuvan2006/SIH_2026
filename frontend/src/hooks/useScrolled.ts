import { useEffect, useState } from "react";

/**
 * True once the window has scrolled past `threshold` pixels.
 *
 * Used to elevate the sticky top bar so it separates from the content
 * instead of floating ambiguously over it. Lives in a hook rather than in
 * one component because both the app shell (Layout) and the signed-out
 * Landing page render their own top bar and need identical behavior.
 */
export function useScrolled(threshold = 8): boolean {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold);
    onScroll(); // sync immediately for restored scroll positions
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);

  return scrolled;
}

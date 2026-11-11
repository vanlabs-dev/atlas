// The stage mode of the home field. Three facts about the browser decide one
// of five modes. A script in <head> writes the mode on <html> before first
// paint; the styles and the Flight component both read that one attribute, so
// they cannot disagree. Import-free, so the node tests can load it.

export const FLIGHT_MODES = ["fly", "overlay", "swipe", "still", "flat"] as const;

/**
 * fly:     wide, motion allowed, WebGL. The stage pins and the scroll flies the camera.
 * overlay: wide, reduced motion, WebGL. The copy over a still field.
 * swipe:   narrow, motion allowed, WebGL. A swipe through the statements moves the camera.
 * still:   narrow, reduced motion, WebGL. The field as a still figure.
 * flat:    no WebGL, any width. The field drawn in 2D.
 * A page with no script has no mode: it gets the stacked layout and no field.
 */
export type FlightMode = (typeof FLIGHT_MODES)[number];

export interface FlightInputs {
  wide: boolean;
  reduced: boolean;
  gl: boolean;
}

export const WIDE_QUERY = "(min-width: 900px)";
export const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
export const FLIGHT_ATTR = "data-flight";

export function flightMode({ wide, reduced, gl }: FlightInputs): FlightMode {
  if (!gl) return "flat";
  if (wide) return reduced ? "overlay" : "fly";
  return reduced ? "still" : "swipe";
}

/**
 * The same rule as flightMode, as the script that runs before first paint and
 * again when the width or the motion setting changes. tests/state.test.ts runs
 * this text against flightMode for every input. The WebGL probe releases its
 * context at once, so it never holds one of the browser's few WebGL slots.
 */
export const FLIGHT_MODE_SCRIPT =
  `(function(){var d=document.documentElement,gl=false;` +
  `try{var c=document.createElement("canvas"),g=c.getContext("webgl2")||c.getContext("webgl");` +
  `if(g){gl=true;var x=g.getExtension("WEBGL_lose_context");if(x)x.loseContext()}}catch(e){}` +
  `var w=matchMedia("${WIDE_QUERY}"),r=matchMedia("${REDUCED_QUERY}");` +
  `function set(){d.setAttribute("${FLIGHT_ATTR}",!gl?"flat":w.matches?(r.matches?"overlay":"fly"):(r.matches?"still":"swipe"))}` +
  `set();if(w.addEventListener){w.addEventListener("change",set);r.addEventListener("change",set)}})()`;

const isMode = (v: string | null): v is FlightMode => (FLIGHT_MODES as readonly string[]).includes(v ?? "");

/** The mode the head script wrote, or null before it ran. Browser only. */
export function readFlightMode(): FlightMode | null {
  const v = document.documentElement.getAttribute(FLIGHT_ATTR);
  return isMode(v) ? v : null;
}

/** Calls back when the mode on <html> changes. Browser only. */
export function watchFlightMode(onChange: () => void): () => void {
  const mo = new MutationObserver(onChange);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: [FLIGHT_ATTR] });
  return () => mo.disconnect();
}

/** What each mode switches on. The component reads these, never the raw facts. */
export const FLIGHT_TRAITS: Record<FlightMode, { gl: boolean; camera: "scroll" | "swipe" | "fixed"; sway: boolean; over: boolean; rise: boolean }> = {
  fly: { gl: true, camera: "scroll", sway: true, over: true, rise: true },
  overlay: { gl: true, camera: "fixed", sway: false, over: true, rise: false },
  swipe: { gl: true, camera: "swipe", sway: true, over: false, rise: true },
  still: { gl: true, camera: "fixed", sway: false, over: false, rise: false },
  flat: { gl: false, camera: "fixed", sway: false, over: false, rise: false },
};

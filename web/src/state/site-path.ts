// The page a route is, for the parts of the layout that mark it (the top
// bar, the bottom bar, the header clock). Import-free, so the node tests can
// load it.
//
// Vercel prerenders the home page as "/index", so usePathname() gives
// "/index" on the server and "/" in the browser. Any markup chosen from the
// raw path then differs, React throws away the server render, and the reset
// of <html> deletes data-flight: the home field never builds. Every part
// that reads the path reads it through this rule.

/** The route's path as the browser shows it: "/index" and a trailing slash removed. */
export function sitePath(pathname: string | null): string {
  const p = (pathname ?? "/").replace(/\/index$/, "").replace(/\/+$/, "");
  return p === "" ? "/" : p;
}

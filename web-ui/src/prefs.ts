/** What the person's system asks for. Both fall back to "no preference" where matchMedia is missing. */

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** True when the browser draws WebGL in software (no GPU): the view then keeps things simple. */
export function isSoftwareGL(gl: WebGLRenderingContext | WebGL2RenderingContext | null): boolean {
  if (!gl) return false;
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "";
  return /swiftshader|llvmpipe|software|basic render/i.test(name);
}

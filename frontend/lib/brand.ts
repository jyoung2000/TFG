/** Build-time brand detection for the WanGP derivative build.
 *
 * When VITE_APP_BRAND=wangp, every user-visible string that says "LTX Desktop"
 * is replaced with "LTX Desktop WanGP" so the derivative app is visually
 * distinct from the upstream Lightricks build.
 */
export const APP_NAME: string =
  import.meta.env.VITE_APP_BRAND === 'wangp' ? 'LTX Desktop WanGP' : 'LTX Desktop'
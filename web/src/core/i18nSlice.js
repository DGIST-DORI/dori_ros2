/**
 * core/i18nSlice.js
 * Zustand slice for language preference.
 * Persisted to localStorage under key 'langPref'.
 */

const LANG_STORAGE_KEY = 'langPref';

function loadLangPref() {
  if (typeof window === 'undefined') return 'auto';
  const stored = window.localStorage?.getItem(LANG_STORAGE_KEY);
  if (stored === 'ko' || stored === 'en' || stored === 'auto') return stored;
  return 'auto';
}

export const i18nSlice = (set) => ({
  langPref: loadLangPref(),

  setLangPref: (lang) => {
    if (!['auto', 'ko', 'en'].includes(lang)) return;
    if (typeof window !== 'undefined') {
      window.localStorage?.setItem(LANG_STORAGE_KEY, lang);
    }
    set({ langPref: lang });
  },
});

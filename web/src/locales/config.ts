import { LanguageAbbreviation, LanguageAbbreviationMap } from '@/constants/common';
import storage from '@/utils/authorization-util';
import dayjs from 'dayjs';
import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { upperFirst } from 'lodash';
import { initReactI18next } from 'react-i18next';
import translation_en from './en';

// The language is based on the .lng file stored in the client's local storage.
// The language stored in the database is for agent template resources, as these resources reside on the server.
// When a user logs in from a different machine, the login page language is the language configured by VITE_DEFAULT_LANGUAGE_CODE.

// Insertion order is the dropdown order, so Simplified Chinese comes first.
const languageImports: Record<string, () => Promise<{ default: any }>> = {
  [LanguageAbbreviation.Zh]: () => import('./zh'),
  [LanguageAbbreviation.En]: () => import('./en'),
};

// A stored tag, a DATABASE setting or the env default can arrive as 'zh',
// 'zh_CN', 'zh-CN' or 'en-US', but only 'zh-Hans' and 'en' are bundled:
// normalize every spelling before it reaches a lookup, otherwise the regional
// tag misses the resource and the UI silently falls back.
const languageAliases: Record<string, string> = {
  zh: LanguageAbbreviation.Zh,
  'zh-cn': LanguageAbbreviation.Zh,
  'zh-hans': LanguageAbbreviation.Zh,
  en: LanguageAbbreviation.En,
  'en-us': LanguageAbbreviation.En,
  'en-gb': LanguageAbbreviation.En,
};

const normalizeLanguage = (lng: string): string =>
  languageAliases[lng.replace(/_/g, '-').toLowerCase()] ?? lng;

const supportedLanguageCodes: Intl.UnicodeBCP47LocaleIdentifier[] =
  Object.keys(languageImports);

export const supportedLanguages = supportedLanguageCodes.map((code) => {
  const locale = new Intl.Locale(code);

  return {
    code,
    locale,
    // The switcher names each language in its own script, so it does not read
    // the generic Intl name (which follows the *browser* locale).
    displayName:
      LanguageAbbreviationMap[code as LanguageAbbreviation] ??
      upperFirst(new Intl.DisplayNames(locale, { type: 'language' }).of(code)!),
  };
});

export const DEFAULT_LANGUAGE_CODE = normalizeLanguage(
  import.meta.env.VITE_DEFAULT_LANGUAGE_CODE || LanguageAbbreviation.Zh,
);

const resources = {
  [LanguageAbbreviation.En]: translation_en,
};

/**
 * Last-resort wording for a key that neither bundle defines: `search.searchApps`
 * must never reach the screen as-is, so the last segment is humanised
 * ("Search apps") and the gap is reported in development.
 *
 * i18next hands the call site's own inline default to this handler when there is
 * one, and that wording always wins — a key called with a default was never at
 * risk of exposing itself.
 */
const humaniseMissingKey = (key: string, inlineDefault?: string): string => {
  if (inlineDefault) {
    return inlineDefault;
  }

  if (import.meta.env.DEV) {
    console.warn(`[i18n] missing translation for "${key}"`);
  }

  const segment = key.split('.').pop() ?? key;
  const words = segment
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();

  return words ? upperFirst(words) : key;
};

const updateDocumentLocale = (lng: string) => {
  document.documentElement.lang = lng;
  document.documentElement.dir = 'ltr';
  dayjs.locale(lng === LanguageAbbreviation.Zh ? 'zh-cn' : lng);
};

i18n
  .use(initReactI18next)
  .use(LanguageDetector)
  .init({
    detection: {
      lookupLocalStorage: 'lng',
      order: ['localStorage'],
      caches: [],
    },
    supportedLngs: supportedLanguageCodes,
    resources,
    // Simplified Chinese is the default; English stays the secondary fallback
    // because its bundle is the one bundled into the entry chunk, so a Chinese
    // bundle that has not finished loading degrades to English instead of
    // showing raw keys.
    fallbackLng: [DEFAULT_LANGUAGE_CODE, LanguageAbbreviation.En],
    parseMissingKeyHandler: humaniseMissingKey,
    interpolation: {
      escapeValue: false,
    },
  });

export const loadLanguageAsync = async (lng: string): Promise<void> => {
  const normalizedLng = normalizeLanguage(lng);

  if (i18n.hasResourceBundle(normalizedLng, 'translation')) {
    return;
  }

  const importFn = languageImports[normalizedLng];
  if (!importFn) {
    console.warn(`Language ${lng} is not supported for lazy loading`);
    return;
  }

  try {
    const module = await importFn();
    const translationData = module.default?.translation || module.default;
    i18n.addResourceBundle(normalizedLng, 'translation', translationData);
  } catch (error) {
    console.error(`Failed to load language ${lng}:`, error);
  }
};

export const changeLanguageAsync = async (
  lng: string,
  options: { persist?: boolean } = {},
): Promise<void> => {
  const { persist = true } = options;
  const normalizedLng = normalizeLanguage(lng);

  if (
    normalizedLng !== LanguageAbbreviation.En &&
    !i18n.hasResourceBundle(normalizedLng, 'translation')
  ) {
    await loadLanguageAsync(normalizedLng);
  }

  if (persist) {
    storage.setLanguage(normalizedLng);
  }

  updateDocumentLocale(normalizedLng);

  await i18n.changeLanguage(normalizedLng);
};

export const initLanguage = async (): Promise<void> => {
  // The first visit has nothing stored, so the default is applied and written
  // back as the persistent choice; later visits keep whatever the user picked.
  const currentLng = normalizeLanguage(
    storage.getLanguage() || DEFAULT_LANGUAGE_CODE,
  );

  await changeLanguageAsync(currentLng);
};

export default i18n;
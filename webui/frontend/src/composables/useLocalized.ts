import { useI18n } from 'vue-i18n'

/**
 * Composable for resolving localized field values from objects
 * that carry an optional `locales` map (schema fields, manifests, etc.).
 *
 * Usage:
 *   const { localize } = useLocalized()
 *   localize(provider, 'name')           // → provider.locales['zh']?.name ?? provider.name
 *   localize(field, 'hint', 'fallback') // → field.locales['zh']?.hint ?? field.hint ?? 'fallback'
 */
export function useLocalized() {
  const { locale } = useI18n()

  /**
   * Resolve a localized value for `field` on `obj`.
   *
   * Resolution order:
   *   1. obj.locales[currentLocale][field]
   *   2. obj[field]
   *   3. fallback (if provided)
   *
   * @param obj       - The object that may contain a `locales` map.
   * @param field     - The property name to resolve (e.g. 'name', 'hint', 'description').
   * @param fallback  - Optional fallback value when neither localized nor default value exists.
   */
  function localize(obj: any, field: string, fallback: string = ''): string {
    const lang = locale.value
    const localized = obj?.locales?.[lang]?.[field]
    if (localized !== undefined && localized !== null && localized !== '') return localized
    const base = obj?.[field]
    if (base !== undefined && base !== null && base !== '') return String(base)
    return fallback
  }

  return { localize }
}

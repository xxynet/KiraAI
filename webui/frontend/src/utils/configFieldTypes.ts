/**
 * Type classification helpers for schema-driven config fields.
 * Shared by ConfigForm (grouping, defaults, validation) and
 * ConfigFieldInput (single-field rendering).
 */

const TEXTAREA_TYPES = new Set(['textarea'])
const MONACO_TYPES = new Set(['json', 'markdown', 'yaml', 'editor'])
const LIST_TYPES = new Set(['list'])
const NUMBER_TYPES = new Set(['integer', 'float', 'number'])
const BOOL_TYPES = new Set(['switch', 'boolean', 'bool'])
const JSON_TYPES = new Set(['object', 'array'])

export function isTextareaLike(type: string): boolean {
  return TEXTAREA_TYPES.has(type)
}

export function isMonacoLike(type: string): boolean {
  return MONACO_TYPES.has(type)
}

export function isListLike(type: string): boolean {
  return LIST_TYPES.has(type)
}

export function isNumberLike(type: string): boolean {
  return NUMBER_TYPES.has(type)
}

export function isBoolLike(type: string): boolean {
  return BOOL_TYPES.has(type)
}

export function isJsonLike(type: string): boolean {
  return JSON_TYPES.has(type)
}

export function isModelSelectLike(type: string): boolean {
  return type === 'model_select'
}

export function isPersonaSelectLike(type: string): boolean {
  return type === 'persona_select'
}

export function isMultiSelectLike(type: string): boolean {
  return type === 'multi_select'
}

export function isSectionLike(type: string): boolean {
  return type === 'section'
}

export function isInfoLike(type: string): boolean {
  return type === 'info'
}

/** Options may come from `options` or the legacy `enum` key. */
export function optionsFor(field: any): any[] {
  const raw = field?.options ?? field?.enum
  return Array.isArray(raw) ? raw : []
}

export function hasOptions(field: any): boolean {
  return optionsFor(field).length > 0
}

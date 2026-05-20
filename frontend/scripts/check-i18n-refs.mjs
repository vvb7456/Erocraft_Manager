#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = path.resolve(new URL('..', import.meta.url).pathname)
const srcDir = path.join(root, 'src')
const localesDir = path.join(srcDir, 'i18n', 'locales')
const defaultLocale = 'zh-CN'
const sourceExts = new Set(['.vue', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'])

function toNamespace(fileName) {
  const stem = fileName.replace(/\.json$/, '')
  return stem.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
}

function readJsonWithDuplicateCheck(filePath) {
  const text = fs.readFileSync(filePath, 'utf8')
  const duplicates = findDuplicateKeys(text)
  return { data: JSON.parse(text), duplicates }
}

function findDuplicateKeys(text) {
  const duplicates = []
  let i = 0

  function skipWs() {
    while (/\s/.test(text[i] ?? '')) i += 1
  }

  function parseString() {
    if (text[i] !== '"') throw new Error(`Expected string at ${i}`)
    i += 1
    let out = ''
    while (i < text.length) {
      const ch = text[i]
      if (ch === '"') {
        i += 1
        return out
      }
      if (ch === '\\') {
        const esc = text[i + 1]
        if (esc === 'u') {
          out += text.slice(i, i + 6)
          i += 6
        } else {
          out += esc
          i += 2
        }
      } else {
        out += ch
        i += 1
      }
    }
    throw new Error('Unterminated string')
  }

  function parsePrimitive() {
    while (i < text.length && !/[\s,\]}]/.test(text[i])) i += 1
  }

  function parseArray(keyPath) {
    i += 1
    skipWs()
    if (text[i] === ']') {
      i += 1
      return
    }
    let index = 0
    while (i < text.length) {
      parseValue([...keyPath, `[${index}]`])
      skipWs()
      if (text[i] === ',') {
        i += 1
        index += 1
        continue
      }
      if (text[i] === ']') {
        i += 1
        return
      }
      throw new Error(`Expected array delimiter at ${i}`)
    }
  }

  function parseObject(keyPath) {
    i += 1
    const keys = new Set()
    skipWs()
    if (text[i] === '}') {
      i += 1
      return
    }
    while (i < text.length) {
      skipWs()
      const key = parseString()
      const fullKey = [...keyPath, key].join('.')
      if (keys.has(key)) duplicates.push(fullKey)
      keys.add(key)
      skipWs()
      if (text[i] !== ':') throw new Error(`Expected colon at ${i}`)
      i += 1
      parseValue([...keyPath, key])
      skipWs()
      if (text[i] === ',') {
        i += 1
        continue
      }
      if (text[i] === '}') {
        i += 1
        return
      }
      throw new Error(`Expected object delimiter at ${i}`)
    }
  }

  function parseValue(keyPath) {
    skipWs()
    if (text[i] === '{') return parseObject(keyPath)
    if (text[i] === '[') return parseArray(keyPath)
    if (text[i] === '"') {
      parseString()
      return
    }
    parsePrimitive()
  }

  parseValue([])
  return duplicates
}

function flattenLeaves(value, prefix = '') {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([key, child]) =>
      flattenLeaves(child, prefix ? `${prefix}.${key}` : key),
    )
  }
  return [prefix]
}

function walkFiles(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name !== 'locales') walkFiles(full, out)
    } else if (sourceExts.has(path.extname(entry.name))) {
      out.push(full)
    }
  }
  return out
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function templateToRegex(template, namespaces) {
  if (!template.includes('${')) return null
  const startsWithKnownNamespace = [...namespaces].some((ns) => template.startsWith(`${ns}.`))
  if (!startsWithKnownNamespace) return null
  const parts = template.split(/\$\{[^}]+\}/g).map(escapeRegExp)
  return new RegExp(`^${parts.join('.*')}$`)
}

function scanSource(namespaces) {
  const files = walkFiles(srcDir)
  const stringRefs = new Set()
  const staticRefs = new Set()
  const dynamicPatterns = []
  const nsAlternation = [...namespaces].map(escapeRegExp).join('|')
  const anyKeyString = new RegExp(`(['"\`])((?:${nsAlternation})\\.[A-Za-z0-9_.\\u4e00-\\u9fff-]+)\\1`, 'g')
  const tCallStatic = /\b(?:t|te)\s*\(\s*(['"])([^'"\n]+)\1/g
  const tmCallStatic = /\btm\s*\(\s*(['"])([^'"\n]+)\1/g
  const tCallTemplate = /\b(?:t|te|tm)\s*\(\s*`([^`]+)`/g
  const anyTemplate = /`([^`]*\$\{[^`]+)`/g

  for (const file of files) {
    const rel = path.relative(root, file)
    const source = fs.readFileSync(file, 'utf8')

    for (const match of source.matchAll(anyKeyString)) {
      stringRefs.add(`${match[2]}\t${rel}`)
    }

    // tm('foo.bar') returns the subtree under foo.bar — treat as prefix
    // pattern so any key starting with `foo.bar.` counts as used and
    // the lookup itself isn't required to be a leaf.
    for (const match of source.matchAll(tmCallStatic)) {
      const key = match[2]
      const ns = key.split('.')[0]
      if (namespaces.has(ns)) {
        dynamicPatterns.push({
          pattern: new RegExp(`^${escapeRegExp(key)}(\\..+)?$`),
          source: `tm('${key}')`,
          file: rel,
        })
      }
    }

    for (const match of source.matchAll(tCallStatic)) {
      const key = match[2]
      const ns = key.split('.')[0]
      if (namespaces.has(ns)) {
        const rest = source.slice(match.index + match[0].length)
        const nextToken = rest.match(/^\s*([+)])/)
        if (nextToken?.[1] === '+') {
          dynamicPatterns.push({
            pattern: new RegExp(`^${escapeRegExp(key)}.*$`),
            source: `${key} + ...`,
            file: rel,
          })
        } else {
          staticRefs.add(`${key}\t${rel}`)
        }
      }
    }

    for (const match of source.matchAll(tCallTemplate)) {
      const template = match[1]
      if (template.includes('${')) {
        const pattern = templateToRegex(template, namespaces)
        if (pattern) dynamicPatterns.push({ pattern, source: template, file: rel })
      } else {
        const ns = template.split('.')[0]
        if (namespaces.has(ns)) staticRefs.add(`${template}\t${rel}`)
      }
    }

    for (const match of source.matchAll(anyTemplate)) {
      const pattern = templateToRegex(match[1], namespaces)
      if (pattern) dynamicPatterns.push({ pattern, source: match[1], file: rel })
    }
  }

  return { stringRefs, staticRefs, dynamicPatterns }
}

function main() {
  const localeNames = fs.readdirSync(localesDir)
    .filter((name) => fs.statSync(path.join(localesDir, name)).isDirectory())
    .sort()
  const defaultDir = path.join(localesDir, defaultLocale)
  const defaultFiles = fs.readdirSync(defaultDir).filter((name) => name.endsWith('.json')).sort()
  const namespaces = new Set(defaultFiles.map(toNamespace))
  const localeKeys = new Map()
  const duplicateErrors = []
  const alignmentErrors = []

  for (const locale of localeNames) {
    const localeDir = path.join(localesDir, locale)
    const files = fs.readdirSync(localeDir).filter((name) => name.endsWith('.json')).sort()
    const defaultFileSet = new Set(defaultFiles)
    const fileSet = new Set(files)
    for (const file of defaultFiles) {
      if (!fileSet.has(file)) alignmentErrors.push(`${locale}: missing file ${file}`)
    }
    for (const file of files) {
      if (!defaultFileSet.has(file)) alignmentErrors.push(`${locale}: extra file ${file}`)
    }

    for (const file of files) {
      const ns = toNamespace(file)
      const fullPath = path.join(localeDir, file)
      const { data, duplicates } = readJsonWithDuplicateCheck(fullPath)
      for (const key of duplicates) duplicateErrors.push(`${locale}/${file}: ${key}`)
      const keys = flattenLeaves(data).map((key) => `${ns}.${key}`).sort()
      localeKeys.set(`${locale}/${ns}`, keys)
    }
  }

  for (const file of defaultFiles) {
    const ns = toNamespace(file)
    const baseline = new Set(localeKeys.get(`${defaultLocale}/${ns}`) ?? [])
    for (const locale of localeNames.filter((name) => name !== defaultLocale)) {
      const current = new Set(localeKeys.get(`${locale}/${ns}`) ?? [])
      for (const key of baseline) {
        if (!current.has(key)) alignmentErrors.push(`${locale}: missing key ${key}`)
      }
      for (const key of current) {
        if (!baseline.has(key)) alignmentErrors.push(`${locale}: extra key ${key}`)
      }
    }
  }

  const allKeys = new Set()
  for (const keys of localeKeys.values()) {
    for (const key of keys) allKeys.add(key)
  }

  const { stringRefs, staticRefs, dynamicPatterns } = scanSource(namespaces)
  const missingRefs = []
  const usedKeys = new Set()

  for (const ref of stringRefs) {
    const [key] = ref.split('\t')
    if (allKeys.has(key)) usedKeys.add(key)
  }

  for (const ref of staticRefs) {
    const [key, file] = ref.split('\t')
    if (allKeys.has(key)) usedKeys.add(key)
    else missingRefs.push(`${key} (${file})`)
  }

  const unusedKeys = [...(localeKeys.get(`${defaultLocale}/common`) ? allKeys : [])]
    .filter((key) => key.split('.')[0] !== '')
    .filter((key) => !usedKeys.has(key))
    .filter((key) => !dynamicPatterns.some(({ pattern }) => pattern.test(key)))
    .sort()

  console.log(`Locales: ${localeNames.join(', ')}`)
  console.log(`Namespaces: ${[...namespaces].sort().join(', ')}`)
  console.log(`Keys: ${allKeys.size} per locale`)
  console.log(`String refs: ${stringRefs.size}`)
  console.log(`Static refs: ${staticRefs.size}`)
  console.log(`Dynamic patterns: ${dynamicPatterns.length}`)

  if (duplicateErrors.length) {
    console.error('\nDuplicate JSON keys:')
    duplicateErrors.forEach((line) => console.error(`  - ${line}`))
  }
  if (alignmentErrors.length) {
    console.error('\nLocale alignment errors:')
    alignmentErrors.forEach((line) => console.error(`  - ${line}`))
  }
  if (missingRefs.length) {
    console.error('\nMissing i18n keys referenced by source:')
    missingRefs.forEach((line) => console.error(`  - ${line}`))
  }
  if (unusedKeys.length) {
    console.error('\nPossibly unused i18n keys (warning, does not fail the check):')
    unusedKeys.forEach((key) => console.error(`  - ${key}`))
  }

  if (duplicateErrors.length || alignmentErrors.length || missingRefs.length) {
    process.exitCode = 1
  } else {
    console.log('i18n references OK')
  }
}

main()

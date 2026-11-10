import { createHash } from 'node:crypto'
import { parse } from '@babel/parser'
import traverseModule from '@babel/traverse'

const traverse = traverseModule.default || traverseModule
const config = JSON.parse(process.argv[2] || '{}')
const maxItems = Number(config.max_items || 10000)
const maxIndexBytes = Number(config.max_index_bytes || 16 * 1024 * 1024)
const gcEveryFactories = Math.max(1, Number(config.gc_every_factories || 32))
const factoryBatchSize = Math.max(1, Number(config.factory_batch_size || 16))
const chunks = []
for await (const chunk of process.stdin) chunks.push(chunk)
const raw = Buffer.concat(chunks)

function finish(payload) {
  let text = JSON.stringify(payload)
  while (
    Buffer.byteLength(text, 'utf8') > maxIndexBytes &&
    payload.items.length
  ) {
    payload.items.pop()
    payload.gaps = [...new Set([...payload.gaps, 'index_size_limit'])]
    payload.status = 'partial'
    text = JSON.stringify(payload)
  }
  process.stdout.write(text)
}

function failed(reason, detail = null) {
  finish({
    schema_version: 1,
    adapter: 'polymerhus-babel-structure',
    adapter_version: '1.0.0',
    parser: {
      name: '@babel/parser',
      version: '8.0.8',
      traverse_version: '8.0.7',
    },
    source: {
      bytes: raw.length,
      sha256: createHash('sha256').update(raw).digest('hex'),
    },
    format: 'unknown',
    status: 'failed',
    counts: {
      import: 0,
      module: 0,
      dependency: 0,
      chunk: 0,
      loader: 0,
    },
    gaps: [reason],
    parse_errors: detail ? [detail] : [],
    items: [],
  })
}

let text
try {
  text = new TextDecoder('utf-8', { fatal: true }).decode(raw)
} catch {
  failed('invalid_utf8')
  process.exit(0)
}

const lineStarts = [0]
for (let index = 0; index < text.length; index += 1) {
  if (text[index] === '\n') lineStarts.push(index + 1)
}

const utf8Prefix = new Uint32Array(text.length + 1)
let byteCount = 0
for (let index = 0; index < text.length;) {
  utf8Prefix[index] = byteCount
  const codePoint = text.codePointAt(index)
  const width = codePoint > 0xffff ? 2 : 1
  const encoded = text.slice(index, index + width)
  const size = Buffer.byteLength(encoded, 'utf8')
  for (let inner = 1; inner < width; inner += 1) {
    utf8Prefix[index + inner] = byteCount
  }
  byteCount += size
  index += width
  utf8Prefix[index] = byteCount
}

function locIndex(position) {
  return lineStarts[position.line - 1] + position.column
}

function nodeRange(node) {
  if (!node?.loc) return null
  return {
    start_utf16: locIndex(node.loc.start),
    end_utf16: locIndex(node.loc.end),
  }
}

function originalRange(node) {
  const range = nodeRange(node)
  if (!range) return null
  return {
    ...range,
    start_byte: utf8Prefix[range.start_utf16],
    end_byte: utf8Prefix[range.end_utf16],
  }
}

function literalRange(node) {
  const range = nodeRange(node)
  if (!range) return null
  const raw = typeof node?.extra?.raw === 'string' ? node.extra.raw : ''
  const quote =
    /^['"]/.test(raw) ? raw[0] : text[range.start_utf16]
  if (quote !== '"' && quote !== "'") {
    return originalRange(node)
  }
  const start =
    text[range.start_utf16] === quote
      ? range.start_utf16
      : range.start_utf16 - 1
  const end = raw
    ? start + raw.length
    : text.indexOf(quote, start + 1) + 1
  return {
    start_utf16: start,
    end_utf16: end,
    start_byte: utf8Prefix[start],
    end_byte: utf8Prefix[end],
  }
}

function sourceText(node, max = 512) {
  const range = nodeRange(node)
  if (!range) return ''
  return text.slice(range.start_utf16, range.end_utf16).slice(0, max)
}

let ast
try {
  ast = parse(text, {
    sourceType: 'unambiguous',
    errorRecovery: true,
    createImportExpressions: true,
    allowAwaitOutsideFunction: true,
    allowReturnOutsideFunction: true,
    plugins: ['topLevelAwait', 'importAttributes'],
  })
} catch (error) {
  failed(error.reasonCode || error.code || 'parse_error', {
    reason: error.reasonCode || error.code || 'parse_error',
    message: String(error.message).slice(0, 300),
    line: error.loc?.line ?? null,
    column: error.loc?.column ?? null,
    byte_start:
      error.loc?.line && error.loc?.column !== undefined
        ? utf8Prefix[
            lineStarts[error.loc.line - 1] + error.loc.column
          ]
        : null,
  })
  process.exit(0)
}

const items = []
const gaps = []
let itemLimitReached = false
let factoriesSinceGc = 0
const pendingFactoryGroups = []

function addGap(reason) {
  gaps.push(reason)
}

function addItem(kind, facts, range) {
  if (items.length >= maxItems) {
    itemLimitReached = true
    addGap('item_limit')
    return false
  }
  if (!range) {
    addGap('invalid_original_range')
    return false
  }
  items.push({
    kind,
    ...facts,
    ...range,
  })
  return true
}

function literalKey(property) {
  const key = property?.key
  if (!key) return null
  if (key.type === 'StringLiteral') return key.value
  if (key.type === 'NumericLiteral') return String(key.value)
  if (key.type === 'Identifier') return key.name
  return null
}

function arrayLiteralIds(node) {
  if (node?.type !== 'ArrayExpression') return []
  return node.elements
    .map((element) => {
      if (element?.type === 'StringLiteral') return element.value
      if (element?.type === 'NumericLiteral') return String(element.value)
      return null
    })
    .filter((value) => value !== null)
}

function functionLike(node) {
  return [
    'FunctionExpression',
    'ArrowFunctionExpression',
    'ObjectMethod',
  ].includes(node?.type)
}

function loaderDependenciesBatch(factories) {
  for (let offset = 0; offset < factories.length; offset += factoryBatchSize) {
    const batch = factories.slice(offset, offset + factoryBatchSize)
    const batchCode =
      'const __polymerhus_factories=['
      + batch.map((factory) => `{${factory.source}}`).join(',')
      + '];'
    let batchAst
    try {
      batchAst = parse(batchCode, {
        sourceType: 'script',
        errorRecovery: true,
      })
    } catch {
      addGap('dependency_batch_parse_failed')
      continue
    }
    const declaration = batchAst.program.body[0]
    const elements =
      declaration?.declarations?.[0]?.init?.elements || []
    if (elements.length !== batch.length) {
      addGap('dependency_batch_parse_failed')
      batchAst = null
      continue
    }
    const states = []
    const stateByRoot = new WeakMap()
    for (let index = 0; index < batch.length; index += 1) {
      const factory = batch[index]
      const property = elements[index]?.properties?.[0]
      const root = property?.value
      const params = root?.params || []
      const loaderParam = params[2]
      if (!loaderParam || loaderParam.type !== 'Identifier') {
        addGap('unsupported_loader_binding')
        continue
      }
      const state = {
        ...factory,
        root,
        property,
        loaderName: loaderParam.name,
        loaderParam,
        loaderBinding: null,
        aliasSeen: false,
        missingBinding: false,
        reassigned: false,
        pendingDependencies: [],
      }
      states.push(state)
      stateByRoot.set(root, state)
    }
    if (!states.length) {
      batchAst = null
      continue
    }
    const stateForPath = (path) => {
      let current = path
      while (current) {
        const state = stateByRoot.get(current.node)
        if (state) return state
        current = current.parentPath
      }
      return null
    }
    traverse(batchAst, {
      CallExpression(path) {
        const state = stateForPath(path)
        if (!state) return
        const callee = path.get('callee')
        if (!callee.isIdentifier({ name: state.loaderName })) return
        const binding = callee.scope.getBinding(callee.node.name)
        if (!binding) {
          state.missingBinding = true
          return
        }
        if (binding.path?.node !== state.loaderParam) return
        state.loaderBinding = binding
        if (!binding.constant) state.reassigned = true
        const argument = path.get('arguments.0')
        if (!argument?.isStringLiteral()) return
        const relativeStart = path.node.start - state.property.start
        const relativeEnd = path.node.end - state.property.start
        if (relativeStart < 0 || relativeEnd < relativeStart) return
        const startUtf16 = state.start_utf16 + relativeStart
        const endUtf16 = state.start_utf16 + relativeEnd
        state.pendingDependencies.push({
          target_module_id: argument.node.value,
          range: {
            start_utf16: startUtf16,
            end_utf16: endUtf16,
            start_byte: utf8Prefix[startUtf16],
            end_byte: utf8Prefix[endUtf16],
          },
        })
      },
    })
    traverse.cache.clear()
    traverse(batchAst, {
      VariableDeclarator(path) {
        const state = stateForPath(path)
        if (!state) return
        const binding = path.scope.getBinding(state.loaderName)
        if (!binding || binding.path?.node !== state.loaderParam) return
        state.loaderBinding = binding
        if (!binding.constant) state.reassigned = true
        const init = path.get('init')
        if (
          init.isIdentifier() &&
          init.scope.getBinding(init.node.name) === binding
        ) {
          state.aliasSeen = true
        }
      },
    })
    traverse.cache.clear()
    batchAst = null
    factoriesSinceGc += batch.length
    if (
      factoriesSinceGc >= gcEveryFactories &&
      typeof global.gc === 'function'
    ) {
      global.gc()
      factoriesSinceGc = 0
    }
    for (const state of states) {
      if (state.missingBinding) addGap('loader_binding_missing')
      if (state.reassigned) addGap('reassigned_loader_binding')
      if (state.aliasSeen) addGap('unsupported_alias_dataflow')
      if (state.reassigned) continue
      for (const dependency of state.pendingDependencies) {
        const range = dependency.range
        addItem(
          'dependency',
          {
            occurrence_key:
              `${state.context.runtime_key}:module:${state.context.module_id}:`
              + `${state.context.module_ordinal}:dep:${range?.start_utf16 ?? 0}`,
            binding_kind: 'webpack_module_loader',
            context_module_id: state.context.module_id,
            context_module_occurrence: state.context.module_occurrence,
            target_module_id: dependency.target_module_id,
            resolution: 'same_registration_candidate',
            ambiguous: false,
          },
          range,
        )
      }
    }
  }
}

function addRegistration(callNode, tableNode, chunkIds, entryIds, kind) {
  const callRange = originalRange(callNode)
  const runtimeKey =
    `${kind}:${callRange?.start_byte ?? 0}:${chunkIds.join(',')}`
  addItem(
    'chunk',
    {
      occurrence_key: `${runtimeKey}:registration`,
      runtime_key: runtimeKey,
      chunk_ids: chunkIds,
      entry_ids: entryIds,
      registration_kind: kind,
    },
    callRange,
  )
  const properties = tableNode?.properties || []
  const factories = []
  let moduleOrdinal = 0
  for (const property of properties) {
    if (property.type !== 'ObjectProperty') continue
    const moduleId = literalKey(property)
    if (moduleId === null || !functionLike(property.value)) continue
    const range = originalRange(property)
    if (!range) continue
    const moduleOccurrence =
      `${runtimeKey}:module:${moduleOrdinal}:${moduleId}`
    addItem(
      'module',
      {
        occurrence_key: moduleOccurrence,
        module_id: moduleId,
        module_ordinal: moduleOrdinal,
        runtime_key: runtimeKey,
        registration_kind: kind,
        context: {
          runtime_key: runtimeKey,
          chunk_ids: chunkIds,
          entry_ids: entryIds,
          registration_start_byte: callRange.start_byte,
        },
      },
      range,
    )
    factories.push({
      source: text.slice(
        originalRange(property).start_utf16,
        originalRange(property).end_utf16,
      ),
      start_utf16: originalRange(property).start_utf16,
      end_utf16: originalRange(property).end_utf16,
      context: {
      runtime_key: runtimeKey,
      module_id: moduleId,
      module_ordinal: moduleOrdinal,
      module_occurrence: moduleOccurrence,
      },
    })
    moduleOrdinal += 1
  }
  pendingFactoryGroups.push(factories)
}

function directWebpackJsonpNode(callee) {
  if (callee?.type === 'Identifier' && callee.name === 'webpackJsonp') {
    return true
  }
  return (
    callee?.type === 'MemberExpression' &&
    !callee.computed &&
    callee.property?.type === 'Identifier' &&
    callee.property.name === 'webpackJsonp'
  )
}

let format = 'unknown'
const hasWebpackMarkers =
  text.includes('webpackJsonp') || text.includes('webpackChunk')

function recordStaticImport(node) {
  format = 'esm'
  const source = node.source
  if (source?.type !== 'StringLiteral') return
  const specifiers = node.specifiers || []
  const importKind =
    specifiers.length === 0
      ? 'side_effect'
      : specifiers.some((item) => item.type === 'ImportNamespaceSpecifier')
        ? 'namespace'
        : specifiers.some((item) => item.type === 'ImportSpecifier') &&
            specifiers.some(
              (item) => item.type === 'ImportDefaultSpecifier',
            )
          ? 'default_and_named'
          : specifiers.some((item) => item.type === 'ImportSpecifier')
            ? 'named'
            : 'default'
  addItem(
    'import',
    {
      occurrence_key:
        `esm:static:${originalRange(source)?.start_byte ?? 0}`,
      subtype: 'static',
      import_kind: importKind,
      specifier: source.value,
      resolved: true,
    },
    literalRange(source),
  )
}

function recordDynamicImport(node) {
  format = 'esm'
  const source = node.source
  const range = literalRange(source)
  if (source?.type === 'StringLiteral') {
    addItem(
      'import',
      {
        occurrence_key: `esm:dynamic:${range?.start_byte ?? 0}`,
        subtype: 'dynamic',
        import_kind: 'dynamic',
        specifier: source.value,
        resolved: true,
      },
      range,
    )
  } else {
    const expression = sourceText(source, 512)
    addItem(
      'import',
      {
        occurrence_key: `esm:dynamic:${range?.start_byte ?? 0}`,
        subtype: 'dynamic',
        import_kind: 'dynamic',
        specifier: null,
        expression,
        expression_truncated:
          expression.length < sourceText(source, Infinity).length,
        resolved: false,
      },
      range,
    )
  }
}

const stack = [ast.program]
while (stack.length) {
  const node = stack.pop()
  if (!node || typeof node !== 'object') continue
  if (node.type === 'ImportDeclaration') {
    recordStaticImport(node)
  } else if (node.type === 'ImportExpression') {
    recordDynamicImport(node)
  } else if (
    node.type === 'VariableDeclarator' &&
    node.id?.type === 'Identifier' &&
    node.id.name === 'installedChunks' &&
    node.init?.type === 'ObjectExpression'
  ) {
    const ids = node.init.properties
      .map((property) => literalKey(property))
      .filter((value) => value !== null)
    addItem(
      'loader',
      {
        occurrence_key:
          `webpack:runtime-state:${originalRange(node)?.start_byte ?? 0}`,
        subtype: 'runtime_state',
        runtime_ids: ids,
      },
      originalRange(node),
    )
  } else if (
    node.type === 'VariableDeclarator' &&
    node.id?.type === 'Identifier' &&
    node.id.name === 'publicPath' &&
    node.init?.type === 'StringLiteral'
  ) {
    addItem(
      'loader',
      {
        occurrence_key:
          `webpack:public-path:${originalRange(node)?.start_byte ?? 0}`,
        subtype: 'public_path',
        value: node.init.value,
        runtime_dependent: false,
      },
      originalRange(node),
    )
  } else if (
    node.type === 'FunctionDeclaration' &&
    node.id?.type === 'Identifier' &&
    node.id.name === 'chunkFilename'
  ) {
    addItem(
      'loader',
      {
        occurrence_key:
          `webpack:chunk-filename:${originalRange(node)?.start_byte ?? 0}`,
        subtype: 'chunk_filename',
        expression: sourceText(node, 512),
        runtime_dependent: true,
      },
      originalRange(node),
    )
  } else if (node.type === 'AssignmentExpression') {
    const left = node.left
    const right = node.right
    const memberName =
      left?.type === 'MemberExpression' && !left.computed
        ? left.property?.name
        : null
    if (memberName === 'p' && right?.type === 'StringLiteral') {
      addItem(
        'loader',
        {
          occurrence_key:
            `webpack:public-path:${originalRange(node)?.start_byte ?? 0}`,
          subtype: 'public_path',
          value: right.value,
          runtime_dependent: false,
        },
        originalRange(node),
      )
    }
    if (memberName === 'u' && functionLike(right)) {
      addItem(
        'loader',
        {
          occurrence_key:
            `webpack:chunk-filename:${originalRange(node)?.start_byte ?? 0}`,
          subtype: 'chunk_filename',
          expression: sourceText(right, 512),
          runtime_dependent: true,
        },
        originalRange(node),
      )
    }
    if (hasWebpackMarkers && memberName === 'src' && right) {
      const expression = sourceText(right, 512)
      if (expression.includes('.js')) {
        addItem(
          'loader',
          {
            occurrence_key:
              `webpack:chunk-filename:${originalRange(node)?.start_byte ?? 0}`,
            subtype: 'chunk_filename',
            expression,
            runtime_dependent: true,
          },
          originalRange(node),
        )
      }
    }
  } else if (node.type === 'CallExpression') {
    const callee = node.callee
    const args = node.arguments || []
    if (
      directWebpackJsonpNode(callee) &&
      args[0]?.type === 'ArrayExpression' &&
      args[1]?.type === 'ObjectExpression'
    ) {
      addRegistration(
        node,
        args[1],
        arrayLiteralIds(args[0]),
        args[2]?.type === 'ArrayExpression'
          ? arrayLiteralIds(args[2])
          : [],
        'webpack3',
      )
      format = 'webpack3'
    } else if (
      callee?.type === 'MemberExpression' &&
      !callee.computed &&
      callee.property?.type === 'Identifier' &&
      callee.property.name === 'push' &&
      args[0]?.type === 'ArrayExpression'
    ) {
      const objectText = sourceText(callee.object, 300)
      const elements = args[0].elements || []
      if (
        elements[0]?.type === 'ArrayExpression' &&
        elements[1]?.type === 'ObjectExpression'
      ) {
        if (objectText.includes('webpackChunk')) {
          addRegistration(
            node,
            elements[1],
            arrayLiteralIds(elements[0]),
            elements[2]?.type === 'ArrayExpression'
              ? arrayLiteralIds(elements[2])
              : [],
            'webpack5',
          )
          format = 'webpack5'
        } else if (objectText.includes('webpackJsonp')) {
          addRegistration(
            node,
            elements[1],
            arrayLiteralIds(elements[0]),
            elements[2]?.type === 'ArrayExpression'
              ? arrayLiteralIds(elements[2])
              : [],
            'webpack4',
          )
          if (format === 'unknown') format = 'webpack4'
        }
      }
    }
  }
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'start', 'end', 'extra', 'errors'].includes(key)) continue
    if (Array.isArray(value)) {
      for (let index = value.length - 1; index >= 0; index -= 1) {
        if (value[index] && typeof value[index] === 'object') {
          stack.push(value[index])
        }
      }
    } else if (value && typeof value === 'object') {
      stack.push(value)
    }
  }
}

const astErrors = ast.errors || []
if (pendingFactoryGroups.length) {
  ast = null
  traverse.cache.clear()
  if (typeof global.gc === 'function') global.gc()
  for (const factories of pendingFactoryGroups) {
    loaderDependenciesBatch(factories)
  }
}

if (
  format === 'unknown' &&
  items.some(
    (item) =>
      item.kind === 'loader' && item.subtype === 'runtime_state',
  )
) {
  format = 'webpack_runtime'
}

const parseErrors = astErrors.map((error) => ({
  reason: error.reasonCode || error.name,
  message: String(error.message).slice(0, 300),
  line: error.loc?.line ?? null,
  column: error.loc?.column ?? null,
  byte_start:
    error.loc?.line && error.loc?.column !== undefined
      ? utf8Prefix[
          lineStarts[error.loc.line - 1] + error.loc.column
        ]
      : null,
}))

items.sort(
  (left, right) =>
    left.start_byte - right.start_byte ||
    left.kind.localeCompare(right.kind) ||
    left.occurrence_key.localeCompare(right.occurrence_key),
)
const counts = {
  import: items.filter((item) => item.kind === 'import').length,
  module: items.filter((item) => item.kind === 'module').length,
  dependency: items.filter((item) => item.kind === 'dependency').length,
  chunk: items.filter((item) => item.kind === 'chunk').length,
  loader: items.filter((item) => item.kind === 'loader').length,
}
let status
if (parseErrors.length) {
  status = items.length ? 'partial' : 'failed'
  addGap('parse_errors')
} else if (itemLimitReached) {
  status = 'partial'
} else if (format === 'unknown') {
  status = items.length ? 'partial' : 'unsupported'
  addGap('unsupported_format')
} else {
  status = 'complete'
}

finish({
  schema_version: 1,
  adapter: 'polymerhus-babel-structure',
  adapter_version: '1.0.0',
  parser: {
    name: '@babel/parser',
    version: '8.0.8',
    traverse_version: '8.0.7',
  },
  source: {
    bytes: raw.length,
    sha256: createHash('sha256').update(raw).digest('hex'),
  },
  format,
  status,
  counts,
  gaps: [...new Set(gaps)],
  parse_errors: parseErrors,
  items,
})

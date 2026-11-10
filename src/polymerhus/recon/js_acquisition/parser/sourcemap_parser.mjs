#!/usr/bin/env node

import fs from 'node:fs';
import { TraceMap } from '@jridgewell/trace-mapping';

const [mapPath, mapUrl, rawLimits] = process.argv.slice(2);
const limits = JSON.parse(rawLimits);
let count = 0;
let truncated = false;

function emit(value) {
  process.stdout.write(JSON.stringify(value) + '\n');
}

function fail(reason) {
  emit({ type: 'error', reason });
  process.exitCode = 2;
  throw new Error(reason);
}

function validateMap(map, depth, sectionPath) {
  if (!map || typeof map !== 'object' || Array.isArray(map)) {
    fail('invalid_map_structure');
  }
  if (map.version !== 3) {
    fail('unsupported_map_version');
  }

  const hasSections = Object.hasOwn(map, 'sections');
  const hasSources = Object.hasOwn(map, 'sources');
  if (hasSections && hasSources) {
    fail('invalid_index_structure');
  }

  if (hasSections) {
    if (depth >= limits.max_section_depth) {
      fail('section_depth_limit');
    }
    if (!Array.isArray(map.sections)) {
      fail('invalid_index_structure');
    }
    for (let sectionOrdinal = 0; sectionOrdinal < map.sections.length; sectionOrdinal++) {
      const section = map.sections[sectionOrdinal];
      if (!section || typeof section !== 'object') {
        fail('invalid_index_structure');
      }
      if (section.url !== undefined) {
        emit({
          type: 'gap',
          gap: 'unsupported_external_section',
          section_path: [...sectionPath, sectionOrdinal],
        });
        continue;
      }
      if (
        !section.map
        || !section.offset
        || !Number.isInteger(section.offset.line)
        || !Number.isInteger(section.offset.column)
      ) {
        fail('invalid_index_structure');
      }
      validateMap(
        section.map,
        depth + 1,
        [...sectionPath, sectionOrdinal],
      );
    }
    return;
  }

  if (!Array.isArray(map.sources)) {
    fail('invalid_sources');
  }
  if (map.sourceRoot !== undefined && typeof map.sourceRoot !== 'string') {
    fail('invalid_source_root');
  }
  for (const source of map.sources) {
    if (source !== null && typeof source !== 'string') {
      fail('invalid_source_type');
    }
  }
  if (
    map.sourcesContent !== undefined
    && !Array.isArray(map.sourcesContent)
  ) {
    fail('invalid_sources_content');
  }
  if (Array.isArray(map.sourcesContent)) {
    for (const content of map.sourcesContent) {
      if (content !== null && typeof content !== 'string') {
        fail('invalid_source_content_type');
      }
    }
  }

  let traced;
  try {
    traced = new TraceMap(map, mapUrl || null);
  } catch {
    fail('parser_library_failed');
  }

  for (let ordinal = 0; ordinal < map.sources.length; ordinal++) {
    if (count >= limits.max_occurrences) {
      if (!truncated) {
        emit({ type: 'gap', gap: 'source_count_limit' });
        truncated = true;
      }
      return;
    }
    const rawName = map.sources[ordinal];
    const contents = map.sourcesContent;
    const content = Array.isArray(contents) ? contents[ordinal] : undefined;
    const state = content === undefined
      ? 'missing'
      : (content === null ? 'null' : (content === '' ? 'empty' : 'text'));
    if (
      typeof content === 'string'
      && Buffer.byteLength(content, 'utf8') > limits.max_source_bytes
    ) {
      fail('source_size_limit');
    }
    emit({
      type: 'occurrence',
      section_path: sectionPath,
      source_ordinal: ordinal,
      raw_name: rawName,
      resolved_source: traced.resolvedSources[ordinal],
      content_state: state,
      content: typeof content === 'string' ? content : null,
    });
    count++;
    if (count >= limits.max_occurrences && ordinal + 1 < map.sources.length) {
      emit({ type: 'gap', gap: 'source_count_limit' });
      truncated = true;
      return;
    }
  }
}

try {
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  validateMap(map, 0, []);
  emit({ type: 'done', occurrence_count: count, truncated });
} catch (error) {
  if (!error || error.message !== process.exitCode) {
    // Known validation paths emit their coded reason above. Never echo raw
    // parser/library messages because they can contain map content.
    if (process.exitCode !== 2) {
      emit({ type: 'error', reason: 'invalid_map_json' });
      process.exitCode = 2;
    }
  }
}

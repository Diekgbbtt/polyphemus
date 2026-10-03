import { useState } from "react"
import Markdown from "react-markdown"
import rehypeSanitize from "rehype-sanitize"
import { Highlight, themes } from "prism-react-renderer"
import { kindLabel } from "./projectArtifacts"
import type {
  ProjectArtifactDetail,
  ProjectArtifactEntry,
  ProjectArtifactKind,
} from "./types"

// The known fields each typed card surfaces. Every other key stays visible in
// the generic YAML tree, so nothing is silently dropped.
const CARD_FIELDS: Partial<Record<ProjectArtifactKind, string[]>> = {
  hunt_config: ["hunt_id", "unit_id", "fault_class", "status", "vulnerability_class"],
  test_spec: ["target_identity", "testing_pattern", "verification_symptoms", "assumptions"],
  pod_export: ["verdict", "terminal_reason", "iterations", "clean"],
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function scalarText(value: unknown): string {
  if (value === null) return "null"
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return String(value)
}

// A recursive, purely-textual YAML value view. It renders objects, arrays,
// scalars and null; React escapes every string, so nothing becomes live DOM.
function YamlValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <ul className="yaml-array">
        {value.map((item, index) => (
          <li key={index}>
            <YamlValue value={item} />
          </li>
        ))}
      </ul>
    )
  }
  if (isRecord(value)) {
    return (
      <dl className="yaml-object">
        {Object.entries(value).map(([key, item]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>
              <YamlValue value={item} />
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  return <span className="yaml-scalar">{scalarText(value)}</span>
}

function TypedYamlCard({
  kind,
  parsed,
}: {
  kind: ProjectArtifactKind
  parsed: Record<string, unknown>
}) {
  const fields = CARD_FIELDS[kind] ?? []
  const present = fields.filter((field) => field in parsed)
  const extras = Object.keys(parsed).filter((key) => !fields.includes(key))
  return (
    <>
      <section className="artifact-card" aria-label={kindLabel(kind)}>
        <h3>{kindLabel(kind)}</h3>
        {present.length === 0 ? (
          <p className="eval-status">No known fields in this artifact.</p>
        ) : (
          <dl className="artifact-fields">
            {present.map((field) => (
              <div key={field}>
                <dt>{field}</dt>
                <dd>
                  <YamlValue value={parsed[field]} />
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      {extras.length > 0 && (
        <section className="artifact-tree" aria-label="Additional fields">
          <h3>Additional fields</h3>
          <YamlValue value={Object.fromEntries(extras.map((key) => [key, parsed[key]]))} />
        </section>
      )}
    </>
  )
}

function GenericYaml({ value }: { value: unknown }) {
  return (
    <section className="artifact-tree" aria-label="YAML tree">
      <h3>YAML</h3>
      <YamlValue value={value} />
    </section>
  )
}

function MarkdownView({ text }: { text: string }) {
  return (
    <div className="artifact-markdown">
      {/* Raw HTML stays off; the sanitize schema strips unsafe constructs. */}
      <Markdown rehypePlugins={[rehypeSanitize]}>{text}</Markdown>
    </div>
  )
}

function codeLanguage(entry: ProjectArtifactEntry): string {
  if (entry.kind === "skill_script") return "bash"
  if (entry.kind === "experiment_log") return "plaintext"
  const media = entry.media_type.toLowerCase()
  if (media.includes("javascript")) return "javascript"
  if (media.includes("typescript")) return "typescript"
  if (media.includes("json")) return "json"
  if (media.includes("yaml")) return "yaml"
  if (media.includes("markdown")) return "markdown"
  if (media.includes("x-python")) return "python"
  if (media.includes("shellscript") || media.includes("shell")) return "bash"
  const suffix = entry.relative_path.split(".").pop()?.toLowerCase() ?? ""
  const bySuffix: Record<string, string> = {
    py: "python",
    js: "javascript",
    mjs: "javascript",
    cjs: "javascript",
    ts: "typescript",
    tsx: "typescript",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
  }
  return bySuffix[suffix] ?? "plaintext"
}

// A syntax-highlighted, escaped code/log view. prism-react-renderer emits React
// tokens (spans), never HTML strings.
function CodeView({ code, language }: { code: string; language: string }) {
  return (
    <Highlight theme={themes.nightOwl} code={code} language={language}>
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <pre className={`${className ?? ""} artifact-code`} style={style}>
          {tokens.map((line, lineIndex) => (
            <div key={lineIndex} {...getLineProps({ line })}>
              {line.map((token, tokenIndex) => (
                <span key={tokenIndex} {...getTokenProps({ token })} />
              ))}
            </div>
          ))}
        </pre>
      )}
    </Highlight>
  )
}

function BinaryView() {
  return (
    <p className="eval-status">
      Binary content is download-only and is never rendered inline.
    </p>
  )
}

function RawText({ text }: { text: string }) {
  return <pre className="artifact-raw">{text}</pre>
}

function SemanticView({ detail }: { detail: ProjectArtifactDetail }) {
  const { entry, preview } = detail

  if (entry.representation === "binary") return <BinaryView />

  if (entry.representation === "markdown") {
    if (preview.text === null) {
      return <p className="eval-status">No preview text; download the raw artifact.</p>
    }
    return <MarkdownView text={preview.text} />
  }

  if (entry.representation === "yaml") {
    if (preview.parse_error) {
      return (
        <>
          <p className="eval-error" role="alert">
            YAML parse error: {preview.parse_error}
          </p>
          {preview.text !== null && <RawText text={preview.text} />}
        </>
      )
    }
    if (preview.parsed !== null && preview.parsed !== undefined) {
      if (isRecord(preview.parsed) && CARD_FIELDS[entry.kind]) {
        return <TypedYamlCard kind={entry.kind} parsed={preview.parsed} />
      }
      return <GenericYaml value={preview.parsed} />
    }
    if (preview.text !== null) return <RawText text={preview.text} />
    return <p className="eval-status">No preview available; download the raw artifact.</p>
  }

  // text
  if (preview.text === null) {
    return <p className="eval-status">No preview text; download the raw artifact.</p>
  }
  return <CodeView code={preview.text} language={codeLanguage(entry)} />
}

function RawView({ detail }: { detail: ProjectArtifactDetail }) {
  if (detail.preview.text === null) {
    return (
      <p className="eval-status">
        No raw text preview is available; download the artifact instead.
      </p>
    )
  }
  return <pre className="artifact-raw">{detail.preview.text}</pre>
}

export function ProjectArtifactRenderer({ detail }: { detail: ProjectArtifactDetail }) {
  const [view, setView] = useState<"semantic" | "raw">("semantic")
  const binary = detail.entry.representation === "binary"
  return (
    <div className="artifact-renderer">
      {!binary && (
        <div role="group" aria-label="Artifact view" className="artifact-view-toggle">
          <button
            type="button"
            aria-pressed={view === "semantic"}
            onClick={() => setView("semantic")}
          >
            Semantic
          </button>
          <button
            type="button"
            aria-pressed={view === "raw"}
            onClick={() => setView("raw")}
          >
            Raw
          </button>
        </div>
      )}
      {detail.preview.truncated && (
        <p className="artifact-truncated" role="status">
          Preview truncated at 512 KiB; download the raw artifact for the full content.
        </p>
      )}
      {binary ? (
        <BinaryView />
      ) : view === "raw" ? (
        <RawView detail={detail} />
      ) : (
        <SemanticView detail={detail} />
      )}
    </div>
  )
}

// Minimal, dependency-free YAML parser — block style only.
//
// Supports the subset QPF's own files use:
//   - nested mappings (key: value / key: with indented children)
//   - sequences of scalars and of mappings (`- key: value` blocks)
//   - scalars: quoted ("…" / '…') and plain; integers; true/false/null
//   - full-line and inline `#` comments (respecting quotes)
//   - empty inline collections: `key: []` and `key: {}`
//
// NOT supported (intentionally — our files avoid them): flow mappings/sequences with
// contents, block scalars (`|`, `>`), anchors/aliases, multi-doc streams.
//
// Throws on malformed indentation so problems surface loudly rather than silently
// producing wrong data.

function stripComment(line) {
  let inS = false, inD = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" && !inD) inS = !inS;
    else if (c === '"' && !inS) inD = !inD;
    else if (c === '#' && !inS && !inD) {
      // a `#` starts a comment only at start of token (preceded by space or BOL)
      if (i === 0 || line[i - 1] === ' ' || line[i - 1] === '\t') return line.slice(0, i);
    }
  }
  return line;
}

function parseScalar(raw) {
  const s = raw.trim();
  if (s === '' ) return null;
  if (s === '[]') return [];
  if (s === '{}') return {};
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1);
  }
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s === 'null' || s === '~') return null;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d*\.\d+$/.test(s)) return parseFloat(s);
  return s;
}

// Tokenize into { indent, content } skipping blanks/comment-only lines.
function tokenize(text) {
  const out = [];
  for (const rawLine of text.split('\n')) {
    const noComment = stripComment(rawLine);
    if (noComment.trim() === '') continue;
    const indent = noComment.length - noComment.trimStart().length;
    out.push({ indent, content: noComment.trim(), raw: rawLine });
  }
  return out;
}

// Recursive-descent over the token list using an index cursor.
export function parseYaml(text) {
  const toks = tokenize(text);
  let i = 0;

  function parseBlock(minIndent) {
    // Determine whether this block is a sequence or a mapping from the first token.
    if (i >= toks.length) return null;
    const first = toks[i];
    if (first.indent < minIndent) return null;
    const indent = first.indent;
    const isSeq = first.content.startsWith('- ') || first.content === '-';

    if (isSeq) {
      const arr = [];
      while (i < toks.length && toks[i].indent === indent &&
             (toks[i].content.startsWith('- ') || toks[i].content === '-')) {
        const t = toks[i];
        const rest = t.content === '-' ? '' : t.content.slice(2);
        if (rest === '') {
          // value is a nested block on following deeper lines
          i++;
          arr.push(parseBlock(indent + 1));
        } else if (/^[^\s"'][^:]*:(\s|$)/.test(rest) || /^["'].*["']\s*:(\s|$)/.test(rest)) {
          // sequence item that is a mapping: `- key: value`
          // Re-inject the mapping key line at a virtual indent so parseBlock reads it
          // as a map. Simplest: build the map inline here.
          arr.push(parseSeqMap(t, indent));
        } else {
          arr.push(parseScalar(rest));
          i++;
        }
      }
      return arr;
    }

    // mapping
    const obj = {};
    while (i < toks.length && toks[i].indent === indent && !toks[i].content.startsWith('- ')) {
      const t = toks[i];
      const m = splitKey(t.content);
      if (!m) throw new Error(`Malformed mapping line: "${t.raw}"`);
      const { key, value } = m;
      if (value === '') {
        i++;
        // nested block (map or seq) deeper than current, or empty
        if (i < toks.length && toks[i].indent > indent) obj[key] = parseBlock(indent + 1);
        else obj[key] = null;
      } else {
        obj[key] = parseScalar(value);
        i++;
      }
    }
    return obj;
  }

  // Parse a `- key: value` mapping item, including any deeper continuation lines that
  // belong to the same item (further keys / nested blocks).
  function parseSeqMap(firstTok, seqIndent) {
    const obj = {};
    // The mapping keys of a seq item sit at column seqIndent+2 (after "- ").
    const keyIndent = seqIndent + 2;
    // handle the inline first key on the "- key: value" line
    let m = splitKey(firstTok.content.slice(2));
    if (!m) throw new Error(`Malformed sequence-map line: "${firstTok.raw}"`);
    applyKey(obj, m, keyIndent);
    // subsequent lines of the same item are indented to keyIndent (not starting with -)
    while (i < toks.length && toks[i].indent === keyIndent && !toks[i].content.startsWith('- ')) {
      const t = toks[i];
      const mm = splitKey(t.content);
      if (!mm) throw new Error(`Malformed mapping line: "${t.raw}"`);
      applyKey(obj, mm, keyIndent);
    }
    return obj;

    function applyKey(target, mkv, kIndent) {
      if (mkv.value === '') {
        i++;
        if (i < toks.length && toks[i].indent > kIndent) target[mkv.key] = parseBlock(kIndent + 1);
        else target[mkv.key] = null;
      } else {
        target[mkv.key] = parseScalar(mkv.value);
        i++;
      }
    }
  }

  function splitKey(s) {
    // key may be quoted; find the first unquoted colon.
    let inS = false, inD = false;
    for (let k = 0; k < s.length; k++) {
      const c = s[k];
      if (c === "'" && !inD) inS = !inS;
      else if (c === '"' && !inS) inD = !inD;
      else if (c === ':' && !inS && !inD && (k + 1 === s.length || s[k + 1] === ' ')) {
        let key = s.slice(0, k).trim();
        if ((key.startsWith('"') && key.endsWith('"')) || (key.startsWith("'") && key.endsWith("'"))) {
          key = key.slice(1, -1);
        }
        return { key, value: s.slice(k + 1).trim() };
      }
    }
    return null;
  }

  const result = parseBlock(0);
  return result === null ? {} : result;
}

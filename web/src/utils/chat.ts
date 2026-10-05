/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import {
  ChatVariableEnabledField,
  EmptyConversationId,
} from '@/constants/chat';
// Type-only: both names are used in annotations only, and a value import here
// makes the Babel module transform fail on this file ("imported binding used in
// a type annotation"), which breaks every suite that imports it.
import type { IConversation, IMessage, Message } from '@/interfaces/database/chat';
import { omit } from 'lodash';
import { v4 as uuid } from 'uuid';
import {
  citationMarkerReg,
  citedChunkIndex,
  normalizeCitationDigits,
  parseCitationIndex,
} from './citation-utils';

export const isConversationIdExist = (conversationId: string) => {
  return conversationId !== EmptyConversationId && conversationId !== '';
};

export const buildMessageUuid = (message: Partial<Message | IMessage>) => {
  if ('id' in message && message.id) {
    return message.id;
  }
  return uuid();
};

export const buildMessageListWithUuid = (messages?: Message[]) => {
  return (
    messages?.map((x: Message | IMessage) => ({
      ...omit(x, 'reference'),
      id: buildMessageUuid(x),
    })) ?? []
  );
};

/**
 * Marker for a conversation that only exists in the browser. Clicking "+" seeds
 * such a conversation so the chat area has something to render, but the server
 * has no session row for it yet — the first send creates the real one. The
 * prefix makes that state readable from the id alone, which the URL (the single
 * source of truth for the open conversation) needs: a bare uuid cannot be told
 * apart from a server-generated one.
 */
export const TEMPORARY_CONVERSATION_PREFIX = 'temp-';

export const generateTemporaryConversationId = () => {
  return `${TEMPORARY_CONVERSATION_PREFIX}${uuid().replace(/-/g, '')}`;
};

export const isTemporaryConversationId = (
  conversationId?: string,
): conversationId is string =>
  !!conversationId && conversationId.startsWith(TEMPORARY_CONVERSATION_PREFIX);

/**
 * True for ids the server can answer for: a non-empty id that is not a local
 * placeholder. Everything that talks to a session endpoint (fetch, patch,
 * completion) must be gated on this.
 */
export const isPersistedConversationId = (
  conversationId?: string,
): conversationId is string =>
  !!conversationId && !isTemporaryConversationId(conversationId);

/**
 * The order the conversation list is read in: the pinned sessions first, then the
 * ones with the most recent activity. It is the rule the list endpoint sorts by,
 * repeated here so an edit made before the server answers — a send, a pin — lands
 * a row exactly where the next refetch will put it.
 */
export function orderConversations(list: IConversation[]): IConversation[] {
  return [...list].sort((a, b) => {
    if (!!a.is_pinned !== !!b.is_pinned) {
      return a.is_pinned ? -1 : 1;
    }
    return (b.update_time ?? 0) - (a.update_time ?? 0);
  });
}

/**
 * Moves a session to the top of its own group, which is what a new turn does to
 * it on the server. `now` is injectable so a test can state the order it expects
 * instead of racing the clock.
 */
export function bumpConversation(
  list: IConversation[],
  sessionId: string,
  now = Date.now(),
): IConversation[] {
  return orderConversations(
    list.map((item) =>
      item.id === sessionId ? { ...item, update_time: now } : item,
    ),
  );
}

/** Pins or unpins a session, which carries it into the pinned group and back. */
export function pinConversation(
  list: IConversation[],
  sessionId: string,
  isPinned: boolean,
): IConversation[] {
  return orderConversations(
    list.map((item) =>
      item.id === sessionId ? { ...item, is_pinned: isPinned } : item,
    ),
  );
}

// When rendering each message, add a prefix to the id to ensure uniqueness.
export const buildMessageUuidWithRole = (
  message: Partial<Message | IMessage>,
) => {
  return `${message.role}_${message.id}`;
};

// Preprocess LaTeX equations to be rendered by KaTeX
// ref: https://github.com/remarkjs/react-markdown/issues/785
//
// Delimiter matching: the closing delimiter is the first `\]` / `\)` in the
// body. This previously carried a negative lookbehind `(?<![a-zA-Z])`, meant to
// stop `\]`/`\)` inside a command name (e.g. `\right]`, `\big)`) from being
// read as the close. That guard protected nothing real and broke the common
// case: `\right]` and `\big)` do not contain `\]` or `\)` at all (the bracket
// and paren there are bare), while the lookbehind did reject a legitimate close
// whenever the body ended in a letter, so `\(a\)` and `\(x < y\)` were left
// unconverted and rendered as literal text. Verified against every case in the
// suite, including the #13134 equation, which matches identically either way.

const BLOCK_MATH_RE = /\\\[([\s\S]*?)\\\]/g;
const INLINE_MATH_RE = /\\\(([\s\S]*?)\\\)/g;

export const preprocessLaTeX = (content: string) => {
  const normalizedContent = content
    .replace(/\\\\\[/g, '\\[')
    .replace(/\\\\\(/g, '\\(')
    .replace(/\\\\\]/g, '\\]')
    .replace(/\\\\\)/g, '\\)')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');

  // `\[ ... \]` is LaTeX *display* math, so it has to land as a block. Emitting
  // `$$...$$` inline on the current line is not enough: remark-math only
  // produces a `math` (flow) node when the opening `$$` starts a line and the
  // body follows on its own lines. Left inline, the equation parses as
  // `inlineMath` and renders inside the surrounding paragraph instead of
  // centred. The surrounding newlines force the flow form.
  const blockProcessedContent = normalizedContent.replace(
    BLOCK_MATH_RE,
    (_, equation) => `\n$$\n${equation.trim()}\n$$\n`,
  );

  // `\( ... \)` is inline math, so `$...$` is the right shape. Trim the padding:
  // micromark tolerates it, but the delimiters read as `$ x $` and a leading or
  // trailing space is exactly the pattern reserved for currency.
  const inlineProcessedContent = blockProcessedContent.replace(
    INLINE_MATH_RE,
    (_, equation) => `$${equation.trim()}$`,
  );

  return inlineProcessedContent;
};

/**
 * Stage banners the Agentic RAG pipeline forwards into the answer stream
 * (`rag/advanced_rag/think_log.py` forwards every INFO record starting with
 * `[`). Matched by prefix only, so new stages need no frontend change beyond
 * adding the tag here.
 *
 * Keep this list complete: a stage tag that is missing here leaks its line into
 * the answer body. The list previously held 7 tags while the pipeline emitted
 * 20+, which is how `[SCA]`, `[QueryRewriter]`, `[SlotResearch]`, `[Planner]`
 * and friends ended up on screen.
 */
export const AGENTIC_LOG_PREFIXES = [
  // orchestration / formalize
  '[Agentic RAG]',
  '[Formalize',
  '[Keywords',
  '[Planner]',
  '[Routing]',
  '[Draft]',
  '[Prefetch]',
  '[StateGuard]',
  '[RAGAgent]',
  '[Naive RAG]',
  '[Action Session',
  '[Compute]',
  // search / retrieval
  '[Direct search',
  '[Hybrid search',
  '[Follow-up search',
  '[Vector search]',
  '[BM25 search]',
  '[Structured search]',
  '[Grep search]',
  '[List chunks]',
  '[Web search]',
  '[Graph exploration]',
  '[Wiki lookup]',
  '[Dataset navigation]',
  '[Compiled expand]',
  '[Memory',
  // sufficiency / composition
  '[SCA]',
  '[QueryRewrite',
  '[QueryRewriter]',
  '[SlotResearch]',
  '[Composing the answer]',
  // Go tool loop (forwarded by the Go server only)
  '[Tool loop]',
  '[Function tool]',
] as const;

/**
 * Any bracketed stage tag, so a stage added later cannot leak a line just because
 * nobody extended the list above. The bracket content must not be a bare number:
 * `[1]` is a footnote or an evidence index, not a stage banner.
 */
const GENERIC_STAGE_TAG_RE = /^\[[^\]]{1,60}\](?![([])/;

/**
 * Progress chatter the tool loop prints around a call without a stage tag
 * ("Running the rag tool...", "Running tool..."). Anchored to the whole line so
 * a real sentence that merely starts with those words is never swallowed.
 */
const AGENTIC_PREAMBLE_RE =
  /^running\s+(?:the\s+)?(?:[\w-]+\s+)?tools?(?:\s*[.…]{1,3})?$/i;

/**
 * Anything that renders a citation, figure or image in the answer. A line like
 * this is never treated as a log even when it carries a stage tag: silently
 * hiding an image, a `Fig. N` reference or an `[ID:n]` citation would damage the
 * answer, whereas leaving a log line in the body is only cosmetic.
 *
 * This veto is deliberate, not an oversight (commit fdfac94cf). The visible
 * consequence is that such a line stays in the answer body, and its `[ID:n]`
 * marker is rendered like any other citation.
 */
const ANSWER_MEDIA_RE =
  /!\[|<img|<figure|<image|\[\s*ID:\s*\d+\s*\]|\bFig(?:ure)?\.?\s*\d/i;

/**
 * A continuation line of a multi-line log record: the pipeline emits records
 * whose body spans lines (e.g. `"[SlotResearch] slot table after round:\n%s"`),
 * and the follow-up lines carry no tag of their own.
 *
 * Attribution is deliberately narrow — table rows and indented/box-drawing
 * continuations only. A broader rule ("anything after a log line is a log line")
 * would swallow the answer itself, which follows the last log line with no
 * separator, and answer bullets start with `-`/`*` so those are excluded too.
 */
const LOG_CONTINUATION_RE = /^(?:\||[ \t]{2,}|[│┃├└┌┐┘┤┬┴─])/;

/**
 * A payload line of a log record: an internal field assignment — the
 * `pre_summary='…'` the compose stage logs on the line after
 * `[Formalize][pre_summary] …evidence_len=N`. The record's first line carries its
 * `[Stage]` tag and is recognised wherever it appears, but the payload line
 * carries no tag at all, and the stage logs immediately before it starts
 * composing — so the answer text ends up glued to that line
 * (`pre_summary=''直接说结论：…`). That is how an internal field reached the answer
 * body: the tagged line was collapsed as a log, its payload was not.
 */
const LOG_FIELD_PAYLOAD_RE =
  /^[a-z][a-z0-9_]{0,31}=(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\S*)/;

/**
 * The same assignment as a list item — `- id=0 type=slot`, which is how the
 * action session renders its slots after `[Action Session:init] …\n<slots>`.
 * Recognised only as a continuation (the whole line belongs to the record),
 * never as a payload to strip: there is no answer glued to these lines, so
 * removing the assignment would leave the rest of the slot table in the answer.
 */
const LOG_LIST_FIELD_RE = /^[-*+]\s+[a-z][a-z0-9_]{0,31}=/;

/** The field assignment a log payload line starts with, `''` when there is none. */
export function matchLogFieldPayload(line: string = ''): string {
  return line.match(LOG_FIELD_PAYLOAD_RE)?.[0] ?? '';
}

/**
 * Drops a leading field assignment and returns what the rest of the line is —
 * the answer, when the payload was glued to it. Dropping the whole line instead
 * would take that answer text with it, which is why the assignment is removed
 * rather than the line.
 */
export function stripLogFieldPayload(line: string = ''): string {
  const payload = matchLogFieldPayload(line);
  return payload ? line.slice(payload.length).replace(/^\s/, '') : line;
}

/** True when a line continues the log record opened by the preceding line. */
export function isAgenticLogContinuation(line: string = ''): boolean {
  const trimmed = line.trimEnd();

  if (trimmed.trim().length === 0 || ANSWER_MEDIA_RE.test(trimmed)) {
    return false;
  }

  return (
    LOG_CONTINUATION_RE.test(trimmed) ||
    LOG_FIELD_PAYLOAD_RE.test(trimmed) ||
    LOG_LIST_FIELD_RE.test(trimmed)
  );
}

/** True when a line is untagged tool-progress chatter. */
export function isAgenticPreambleLine(line: string = ''): boolean {
  return AGENTIC_PREAMBLE_RE.test(line.trim());
}

/**
 * True when a line belongs in the collapsed progress panel. Answer-bearing
 * lines (figures, images, citations) are excluded first so extraction can never
 * remove content the user is meant to read.
 */
export function isAgenticLogLine(line: string = ''): boolean {
  const trimmed = line.trim().replace(/^[-*+]\s+/, '');

  if (ANSWER_MEDIA_RE.test(trimmed)) {
    return false;
  }

  return (
    AGENTIC_LOG_PREFIXES.some((prefix) => trimmed.startsWith(prefix)) ||
    isBareStageTagLine(trimmed) ||
    isAgenticPreambleLine(trimmed)
  );
}

/** True for a bracketed stage tag that is not in the list above. */
function isBareStageTagLine(trimmed: string): boolean {
  const match = trimmed.match(GENERIC_STAGE_TAG_RE);

  return match !== null && !/^\[\s*\d+\s*\]$/.test(match[0]);
}

// Fenced code blocks must never be rewritten: a shell snippet or a log sample
// can legitimately start a line with one of the prefixes above.
const CODE_FENCE_RE = /^\s*(```|~~~)/;
// Inline code spans and existing TeX must be left untouched by the caret pass.
const CODE_OR_MATH_SEGMENT_RE = /(`[^`]*`|\$\$[\s\S]*?\$\$|\$[^$\n]*\$)/g;
// `1.5mm^2`, `10^-6`, `m^{3}`: a unit/number exponent typed as plain text.
const BARE_CARET_EXPONENT_RE =
  /([0-9A-Za-z)\]])\^(\{[^}\s]{1,12}\}|[+-]?[0-9]{1,3}|[A-Za-z])/g;
// One think line arrives as Go's `…<br>` (trailing break) or Python's
// `<br>…\n` (leading break), so a log line can only be recognised after
// splitting the physical line on the break tags as well.
const BREAK_TAG_RE = /<br\s*\/?>/gi;
// Placeholder marking where the collapsed log panel belongs; substituted once
// the final line count is known.
const LOG_BLOCK_SENTINEL = '@@agentic-log-block@@';

/** Splits text into physical lines, then each line on `<br>` boundaries. */
const splitLogLines = (text: string = ''): string[] =>
  text
    .split(/\r?\n/)
    .flatMap((line) => line.split(BREAK_TAG_RE))
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);

/** True when the first line of a block is an Agentic RAG log line. */
export function isAgenticLogText(text: string = ''): boolean {
  const firstLine = splitLogLines(text)[0];

  return firstLine !== undefined && isAgenticLogLine(firstLine);
}

/** Number of Agentic RAG log lines in a block of text. */
export function countAgenticLogLines(text: string = ''): number {
  return splitLogLines(text).filter((line) => isAgenticLogLine(line)).length;
}

const fillLogCount = (summary: string, count: number) =>
  summary.replace(/\{\{\s*num\s*\}\}/g, String(count));

// The leading stage tag is rendered as inline code: it keeps the tag visually
// distinct (and stops markdown from reading `[Tag]` as a link reference).
const stripTagToCode = (line: string) =>
  line.replace(/^(\[[^\]]{1,60}\])(\S?.*)$/, '`$1`$2');

/**
 * Separates a generated `<details>` panel from the text around it.
 *
 * CommonMark keeps an HTML block open until a blank line, so an answer glued to
 * a panel's closing tag — the pipeline emits `</think>` immediately before the
 * answer, which becomes `</details>答案` — is read as raw HTML and its markdown
 * is never parsed: `**0.0991 Ω/km**` reaches the screen with its asterisks
 * intact. A panel is also only recognised as a block when its own tag starts a
 * line, hence both edges.
 */
const detachPanels = (text: string) =>
  text
    .replace(/([^\n])(<details\b)/gi, '$1\n\n$2')
    .replace(/(<\/details>)([^\n])/gi, '$1\n\n$2');

const buildAgenticLogBlock = (summary: string, logs: string[]) =>
  [
    `<details class="agentic-log"><summary>${fillLogCount(
      summary,
      logs.length,
    )}</summary>`,
    '',
    // The blank lines are load-bearing: markdown nested in a raw HTML block is
    // only parsed once the block is interrupted, so the log lines below stay
    // real markdown (bold, code fences, links) instead of one unformatted blob.
    ...logs.map(stripTagToCode),
    '',
    '</details>',
  ].join('\n');

/**
 * Removes the whitespace and empty markup that extraction leaves at the edges of
 * the answer, so the body starts on real content instead of stray line breaks.
 */
export function trimExtractionResidue(text: string = '') {
  const LEADING = /^(?:\s|&nbsp;|<br\s*\/?>|<p>\s*<\/p>|<p><\/p>)+/i;
  const TRAILING = /(?:\s|&nbsp;|<br\s*\/?>|<p>\s*<\/p>|<p><\/p>)+$/i;

  return text.replace(LEADING, '').replace(TRAILING, '');
}

export function replaceThinkToSection(
  text: string = '',
  summary: string = 'Thinking...',
  logSummary?: string,
) {
  // The closing tag is optional on purpose: while an answer streams the block
  // is still open, and leaving it unhandled would print the raw reasoning and
  // pipeline logs into the answer until the closer arrives.
  const pattern = /<think>([\s\S]*?)(?:<\/think>|$)/g;

  const result = text.replace(pattern, (_match, thinkContent: string) => {
    const body = thinkContent.trim();
    if (body.length === 0) {
      return '';
    }
    // Agentic RAG progress logs reach the UI wrapped in <think> markers. They
    // are diagnostics, not reasoning, so they get their own summary and the
    // monospaced log list instead of the generic "Thought" panel.
    if (logSummary && isAgenticLogText(body)) {
      return buildAgenticLogBlock(logSummary, splitLogLines(body));
    }
    // Same blank-line rule as the log panel: without it the reasoning body is
    // treated as raw HTML and its markdown is never rendered.
    return `<details class="think"><summary>${summary}</summary>\n\n${body}\n\n</details>`;
  });

  return detachPanels(result);
}

// Strip <think> reasoning blocks so only the answer text remains.
// The second replace handles a streaming message whose block is still unclosed.
export function removeThinkSection(text: string = '') {
  return text
    .replace(/<think>[\s\S]*?<\/think>/g, '')
    .replace(/<think>[\s\S]*$/, '')
    .trim();
}

export function replaceRetrievingToSection(
  text: string = '',
  summary: string = 'Retrieving...',
) {
  const pattern = /<retrieving>([\s\S]*?)<\/retrieving>/g;

  const result = text.replace(
    pattern,
    (_match, retrievingContent: string) =>
      `<details class="retrieving"><summary>${summary}</summary>\n\n${retrievingContent.trim()}\n\n</details>`,
  );

  return detachPanels(result);
}

/**
 * Collapses bare Agentic RAG progress lines into one collapsed `<details>`
 * block, placed where the first line appeared, so the answer body only keeps
 * the parts the user should read. Lines inside fenced code blocks are kept, and
 * a line that mixes a log with real content keeps the content.
 */
export function replaceAgenticLogsToSection(
  text: string = '',
  summary: string = 'Agentic RAG log',
) {
  if (!text || !text.includes('[')) {
    return text;
  }

  const kept: string[] = [];
  const logs: string[] = [];
  let inserted = false;
  let inFence = false;
  let detailsDepth = 0;
  // True while the previous line was a log record, so a following untagged
  // continuation line (table row / indented body) can be attributed to it.
  let logRunOpen = false;

  text.split(/\r?\n/).forEach((line) => {
    // A collapsed panel is finished output, not source text: re-scanning its
    // lines built a second panel out of them and left the first one empty, so a
    // reasoning block that already became a panel is passed through untouched.
    if (/<details\b/i.test(line)) {
      detailsDepth += 1;
      logRunOpen = false;
    }
    if (detailsDepth > 0) {
      kept.push(line);
      if (/<\/details>/i.test(line)) {
        detailsDepth -= 1;
      }
      return;
    }
    if (CODE_FENCE_RE.test(line)) {
      inFence = !inFence;
      kept.push(line);
      logRunOpen = false;
      return;
    }
    if (inFence) {
      kept.push(line);
      logRunOpen = false;
      return;
    }

    const remaining: string[] = [];
    let sawLog = false;
    for (const segment of line.split(BREAK_TAG_RE)) {
      if (isAgenticLogLine(segment)) {
        sawLog = true;
        logs.push(segment.trim());
        continue;
      }
      remaining.push(segment);
    }

    if (!sawLog) {
      // The payload line of the record opened above is a field assignment, and
      // the stage logs it right before composing — so the answer is glued to it
      // (`pre_summary=''直接说结论：…`). The assignment goes to the panel and the
      // rest of the line stays in the answer: dropping the whole line would take
      // the answer's first paragraph with it.
      const payload = logRunOpen ? matchLogFieldPayload(line) : '';
      if (payload) {
        logs.push(payload.trim());
        logRunOpen = false;
        const rest = stripLogFieldPayload(line);
        if (rest.length > 0) {
          kept.push(rest);
        }
        return;
      }
      // A continuation of the record opened by the previous line belongs to the
      // panel as well; anything else ends the run and stays in the answer.
      if (logRunOpen && isAgenticLogContinuation(line)) {
        logs.push(line.trim());
        return;
      }
      logRunOpen = false;
      kept.push(line);
      return;
    }
    logRunOpen = true;
    if (!inserted) {
      inserted = true;
      kept.push(LOG_BLOCK_SENTINEL);
    }
    // A pure log line leaves nothing behind; a mixed line keeps its text, with
    // the break tags that surrounded the removed segments trimmed away.
    const rest = remaining
      .join('<br>')
      .replace(/^(?:<br\s*\/?>|\s)+|(?:<br\s*\/?>|\s)+$/gi, '');
    if (rest.length > 0) {
      kept.push(rest);
    }
  });

  if (logs.length === 0) {
    return text;
  }

  return detachPanels(
    trimExtractionResidue(
      kept
        .join('\n')
        .replace(LOG_BLOCK_SENTINEL, buildAgenticLogBlock(summary, logs))
        .replace(/\n{3,}/g, '\n\n'),
    ),
  );
}

/**
 * Promotes caret exponents typed as plain text (`1.5mm^2`, `10^-6`) into inline
 * TeX so KaTeX renders real superscripts. Fenced code, inline code spans and
 * existing `$…$` math are left alone, which keeps this safe for both user
 * questions and model answers.
 */
export function promoteCaretExponentsToLaTeX(text: string = '') {
  if (!text || !text.includes('^')) {
    return text;
  }

  let inFence = false;

  return text
    .split('\n')
    .map((line) => {
      if (CODE_FENCE_RE.test(line)) {
        inFence = !inFence;
        return line;
      }
      if (inFence) {
        return line;
      }
      return line
        .split(CODE_OR_MATH_SEGMENT_RE)
        .map((segment, index) =>
          // Odd indices are the captured code spans / math segments.
          index % 2 === 1
            ? segment
            : segment.replace(
                BARE_CARET_EXPONENT_RE,
                (_match, base: string, exponent: string) => {
                  // `m^{3}` already carries its own braces; `mm^2` does not.
                  const value =
                    exponent.startsWith('{') && exponent.endsWith('}')
                      ? exponent.slice(1, -1)
                      : exponent;

                  return `${base}$^{${value}}$`;
                },
              ),
        )
        .join('');
    })
    .join('\n');
}

// Placeholder markers used internally to protect standalone < and > from
// DOMPurify stripping. These Unicode symbols (U+27E8/U+27E9) are extremely
// unlikely to appear in normal user input.
const LT_MARKER = '\u27E8LT\u27E9';
const GT_MARKER = '\u27E8GT\u27E9';

/**
 * Escape standalone < and > that are NOT part of a matched <...> pair,
 * so that DOMPurify won't strip them as HTML tags.
 * Only brackets inside text segments (outside complete tags) are escaped;
 * matched <...> tags are left intact for DOMPurify to handle.
 */
export function escapeUnmatchedAngleBrackets(content: string): string {
  if (!content) return content;

  const segments: string[] = [];
  const tags: string[] = [];
  let lastIndex = 0;

  const regex = /<[^>]*>/g;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    segments.push(content.slice(lastIndex, match.index));
    tags.push(match[0]);
    lastIndex = regex.lastIndex;
  }
  segments.push(content.slice(lastIndex));

  const escapedSegments = segments.map((seg) =>
    seg.replace(/</g, LT_MARKER).replace(/>/g, GT_MARKER),
  );

  return escapedSegments
    .map((seg, i) => (i < tags.length ? seg + tags[i] : seg))
    .join('');
}

/**
 * Restore escaped angle bracket markers back to HTML entities (&lt;/&gt;).
 * Must be called *after* preprocessLaTeX (which would otherwise convert
 * &lt;/&gt; back to raw <, >).
 */
export function unescapeAngleBrackets(content: string): string {
  if (!content) return content;
  return content
    .replace(new RegExp(LT_MARKER, 'g'), '&lt;')
    .replace(new RegExp(GT_MARKER, 'g'), '&gt;');
}

export function setInitialChatVariableEnabledFieldValue(
  field: ChatVariableEnabledField,
) {
  return field !== ChatVariableEnabledField.MaxTokensEnabled;
}

const ShowImageFields = ['image', 'table'];

export function showImage(filed?: string) {
  return ShowImageFields.some((x) => x === filed);
}

export function setChatVariableEnabledFieldValuePage() {
  const variableCheckBoxFieldMap = Object.values(
    ChatVariableEnabledField,
  ).reduce<Record<string, boolean>>((pre, cur) => {
    pre[cur] = cur !== ChatVariableEnabledField.MaxTokensEnabled;
    return pre;
  }, {});

  return variableCheckBoxFieldMap;
}

const oldReg = /(#{2}[0-9\u0660-\u0669\u06F0-\u06F9]+\${2})/g;
export const currentReg = citationMarkerReg;
export { citedChunkIndex, normalizeCitationDigits, parseCitationIndex };

// To be compatible with the old index matching mode
export const replaceTextByOldReg = (text: string) => {
  return text?.replace(oldReg, (substring: string) => {
    return `[ID:${substring.slice(2, -2)}]`;
  });
};

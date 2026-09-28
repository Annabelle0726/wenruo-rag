//
//  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.
//

package chunker

import (
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// A standards document filed under a human file name ("450/750V聚氯乙烯绝缘电缆
// 采购标准+第2部分：专用技术规范_2.pdf") loses its identity the moment its cover
// page is sliced away from its parameter tables. The surviving chunk keeps only
// the file name, which reads like a procurement standard, so the answering model
// concludes the knowledge base holds "only a procurement standard" instead of the
// Q/GDW body it was asked about — even though the retrieved chunk came from that
// very standard.
//
// Every chunk therefore carries the document-level context — standard number,
// document title, enclosing section — as a text prefix:
//
//	[标准号: Q/GDW 73289.2-2026 | 文档: 450/750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范 | 章节: 表1 技术参数特性表] 内容...
//
// The prefix is part of the chunk text rather than a separate metadata field, so
// it reaches the index through the normal path: the Tokenizer derives
// content_ltks and the embedding input from the text, and the retrieval stage
// returns that same text as content_with_weight. A question naming the standard
// number therefore matches the chunk lexically, semantically, and visibly.
//
// Injection is deliberately conditional: a document that declares no standard
// number keeps byte-identical chunks, so ordinary documents are untouched.

// contextPrefixOpen starts every injected prefix. It is the format's opening marker, NOT
// an idempotency authority: whether a chunk already carries a prefix is decided by
// verifiedPrefixExtent (see prefixprovenance.go), because a document's own body can start
// with these exact bytes.
const contextPrefixOpen = "[标准号: "

const (
	// standardScanChunkCap / standardScanRuneCap bound the scan window. A
	// standard number identifying the document is declared on the cover page
	// (and often repeated in the running header), so the leading chunks are
	// enough; the rune cap keeps the scan cheap for pathological chunk sizes.
	standardScanChunkCap = 8
	standardScanRuneCap  = 4000

	// Context fields are display text inside a retrieval chunk; they are capped
	// so a pathological file name cannot dominate the chunk's token budget.
	contextTitleRuneCap   = 60
	contextSectionRuneCap = 40
)

// standardPrefixAlternation is the allowlist of standard-designation prefixes
// (Chinese national/industry/enterprise standards plus the common international
// bodies). An allowlist rather than a permissive pattern keeps ordinary technical
// prose — motor ratings such as "450/750V" or cable models — from being read as a
// standard number.
//
// MT (煤炭行业标准) is here because its absence was worse than a missing feature: a
// coal standard's own number was invisible to the scan, so detection fell through
// to the first *cited* standard in the front matter and stamped every chunk of
// 《MT/T 818.11-2009》 with a "标准号" the document does not own — a field the
// answering prompt is told to treat as authoritative. Keep this list aligned with
// _STANDARD_PREFIXES in rag/nlp/doc_context.py.
const standardPrefixAlternation = `Q/[A-Z]{2,6}|GB|DL|NB|MT|JB|YD|JJG|JJF|HG|SH|SY|TB|CJ|JG|JGJ|CECS|IEC|ISO|IEEE|EN|BS|DIN|JIS|ASTM|ANSI|UL|API`

var (
	// standardIDRE matches "<prefix><optional /T> <number>[.<number>...] - <year>".
	// Whitespace is allowed on both sides of the separator because cover pages
	// routinely wrap "Q/GDW 73289.2" away from its year, and the dash itself may
	// be an ASCII hyphen or any of the Unicode dash variants used in print.
	standardIDRE = regexp.MustCompile(
		`(?i)(` + standardPrefixAlternation + `)(/[A-Z]{1,3})?\s*([0-9]{1,6}(?:\.[0-9]{1,3})*)\s*[-‐‑‒–—]\s*([0-9]{4})`)

	// enterpriseStandardIDRE matches the year-less form. Only enterprise
	// standards (Q/...) are accepted without a year: their designation is
	// unambiguous, whereas a bare "GB 1234" is more likely a table value.
	enterpriseStandardIDRE = regexp.MustCompile(
		`(?i)(Q/[A-Z]{2,6})(/[A-Z]{1,3})?\s*([0-9]{1,6}(?:\.[0-9]{1,3})*)`)

	// sectionHeadingRE matches the lines that introduce a clause, appendix or
	// table/figure inside a standard. Group 1 is the heading marker; group 2 is
	// the heading text, which must be separated from the marker, so a body
	// sentence that merely starts with "图1所示" is not read as a heading.
	//
	// The numbered marker is additionally validated against a Chinese heading text
	// (see headingOf) so measurements like "1.5 mm2 铜芯线" are not mistaken for
	// headings.
	sectionHeadingRE = regexp.MustCompile(
		`^(?:#{1,6}[ \t]*)?(表\s*[0-9]+(?:\.[0-9]+)*|图\s*[0-9]+(?:\.[0-9]+)*|附录\s*[A-Za-z0-9一二三四五六七八九十]{1,4}|第\s*[0-9一二三四五六七八九十百]{1,4}\s*(?:章|节|部分|篇|条)|[0-9]+(?:\.[0-9]+)*)(?:[ \t、.．:：]+(.*))?$`)
)

// attachDocumentContext prefixes every chunk with the document-level context
// when the document declares a standard number. Chunks of documents without a
// declared standard number are left byte-identical.
//
// docName is the source document name/key; the chunk texts supply the cover-page
// standard number. Media-only chunks (no text) are skipped: their retrievable
// content lives in the media-context fields, which this prefix does not cover.
func attachDocumentContext(chunks []map[string]any, docName string) {
	if len(chunks) == 0 {
		return
	}
	texts := make([]string, len(chunks))
	for i, ck := range chunks {
		texts[i], _ = ck["text"].(string)
	}

	standardID := detectStandardID(docName, texts)
	if standardID == "" {
		return
	}
	title := documentTitle(docName)
	sections := documentSections(texts)

	for i := range chunks {
		text, ok := chunks[i]["text"].(string)
		if !ok || strings.TrimSpace(text) == "" {
			continue
		}
		if verifiedPrefixExtent(chunks[i]) != nil {
			// Provenance says a prefix is already here. The TEXT cannot say it: a body that
			// happens to start with contextPrefixOpen is a body, and skipping it would leave
			// the chunk without the standard number it belongs to.
			continue
		}
		header := renderDocumentContext(standardID, title, sections[i])
		chunks[i]["text"] = header + text
		recordPrefix(chunks[i], header, prefixKindLegacy, legacyPrefixVersion)
	}
}

// detectStandardID returns the normalized standard number the document declares,
// or "" when none is found. The document name is scanned first so a standard
// number embedded in the file name wins over a chance match deep in the body.
func detectStandardID(docName string, texts []string) string {
	var b strings.Builder
	b.WriteString(strings.Join(strings.Fields(docName), " "))
	b.WriteString("\n")

	budget := standardScanRuneCap
	for i, text := range texts {
		if i >= standardScanChunkCap || budget <= 0 {
			break
		}
		window := []rune(text)
		if len(window) > budget {
			window = window[:budget]
		}
		b.WriteString(string(window))
		b.WriteString("\n")
		budget -= len(window)
	}

	scan := b.String()
	if id := firstStandardID(standardIDRE, scan, true); id != "" {
		return id
	}
	return firstStandardID(enterpriseStandardIDRE, scan, false)
}

// firstStandardID returns the first accepted designation in text. requireYear
// selects the year-bearing pattern; the year-less pattern is only consulted as a
// fallback so an explicit "…-2026" always wins over a bare number.
func firstStandardID(re *regexp.Regexp, text string, requireYear bool) string {
	for _, match := range re.FindAllStringSubmatchIndex(text, -1) {
		if !standardBoundaryBefore(text, match[0]) {
			continue
		}
		prefix := text[match[2]:match[3]]
		qualifier := submatch(text, match, 4)
		number := text[match[6]:match[7]]
		year := submatch(text, match, 8)
		if requireYear && year == "" {
			continue
		}
		if !requireYear && countDigits(number) < 3 {
			continue
		}
		id := strings.ToUpper(prefix) + strings.ToUpper(qualifier) + " " + number
		if year != "" {
			id += "-" + year
		}
		return id
	}
	return ""
}

func submatch(text string, match []int, group int) string {
	if len(match) <= group+1 || match[group] < 0 {
		return ""
	}
	return text[match[group]:match[group+1]]
}

// standardBoundaryBefore rejects a designation glued to a preceding ASCII word,
// so "GENERAL 100-2020" cannot match through its inner "EN". Only ASCII word
// characters count as glue: Chinese prose does not separate words with spaces, so
// the far more common "依据GB/T 12706.1-2020的规定" must still match.
func standardBoundaryBefore(text string, start int) bool {
	if start == 0 {
		return true
	}
	r, _ := utf8.DecodeLastRuneInString(text[:start])
	if r >= utf8.RuneSelf {
		return true
	}
	return !(r >= '0' && r <= '9' || r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z')
}

func countDigits(s string) int {
	n := 0
	for _, r := range s {
		if unicode.IsDigit(r) {
			n++
		}
	}
	return n
}

// documentTitle reduces the document name to a readable title by dropping the
// file extension.
//
// The name is deliberately NOT split on path separators: cable-standards
// documents carry the voltage rating in their name
// ("450/750V聚氯乙烯绝缘电缆采购标准…"), so treating that slash as a directory
// separator would truncate the title to "750V…".
func documentTitle(docName string) string {
	title := strings.TrimSpace(docName)
	if title == "" {
		return ""
	}
	title = strings.TrimSpace(strings.TrimSuffix(title, filepath.Ext(title)))
	return truncateRunes(strings.Join(strings.Fields(title), " "), contextTitleRuneCap)
}

// documentSections returns the section in effect for each chunk, in reading
// order. A chunk that opens with a heading names its own section; the following
// chunks inherit it until the next heading appears.
//
// The walk is over chunk order rather than an extracted outline: it works for
// every chunker variant, including the parser-driven ones that carry no outline,
// and a table chunk keeps its own caption ("表1 技术参数特性表") as its section.
func documentSections(texts []string) []string {
	sections := make([]string, len(texts))
	current := ""
	for i, text := range texts {
		if heading := firstHeadingLine(text); heading != "" {
			current = heading
		}
		sections[i] = current
	}
	return sections
}

// firstHeadingLine returns the heading formed by the chunk's first non-empty
// line, or "". Only the first line is considered: a heading introduces the text
// that follows it, so a heading-shaped line further down the chunk is body
// content (a table cell, a parameter row), not the chunk's section.
func firstHeadingLine(text string) string {
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		return headingOf(line)
	}
	return ""
}

// headingOf reports whether a standalone line is a section heading, returning
// its display form.
func headingOf(line string) string {
	match := sectionHeadingRE.FindStringSubmatch(line)
	if match == nil {
		return ""
	}
	marker := strings.Join(strings.Fields(match[1]), "")
	tail := strings.Join(strings.Fields(match[2]), " ")

	// A numbered heading is only trusted when its heading text STARTS with Chinese:
	// that is the shape of a real clause heading ("5.1 电缆结构"), while parameter
	// rows lead with a unit ("1.5 mm2 铜芯线", "0.6/1 kV 电缆"). A missing section is
	// far better than a section that names a measurement.
	if numericHeadingRe.MatchString(marker) && !cjkLeadRe.MatchString(tail) {
		return ""
	}
	heading := marker
	if tail != "" {
		heading = marker + " " + tail
	}
	return truncateRunes(heading, contextSectionRuneCap)
}

var (
	numericHeadingRe = regexp.MustCompile(`^[0-9]+(?:\.[0-9]+)*$`)
	cjkLeadRe        = regexp.MustCompile(`^[\p{Han}]`)
)

// renderDocumentContext builds the prefix line. Missing fields are omitted so the
// prefix never contains an empty label.
func renderDocumentContext(standardID, title, section string) string {
	parts := []string{"标准号: " + standardID}
	if title != "" {
		parts = append(parts, "文档: "+title)
	}
	if section != "" {
		parts = append(parts, "章节: "+section)
	}
	return "[" + strings.Join(parts, " | ") + "] "
}

func truncateRunes(s string, limit int) string {
	if limit <= 0 || utf8.RuneCountInString(s) <= limit {
		return s
	}
	return string([]rune(s)[:limit])
}

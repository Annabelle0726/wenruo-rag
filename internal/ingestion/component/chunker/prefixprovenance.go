package chunker

import (
	"fmt"

	"github.com/cespare/xxhash/v2"
)

// The injected-prefix provenance contract, mirroring `rag/nlp/doc_context.py`.
//
// A producer that injects a prefix records four fields on the chunk: the kind, the
// grammar version, the exact code-point extent of the injected prefix, and a hash of
// exactly those characters. A consumer that wants the passage's OWN text slices
// content_with_weight[extent:] after verifying the hash, and otherwise treats the whole
// content as evidence.
//
// The text is never parsed to recover the boundary. A document's own prose can begin with
// bytes identical to a prefix, so the text cannot say whether a prefix was injected -
// which is also why attachDocumentContext asks this contract, not the text, whether a
// prefix is already present.
const (
	prefixKindField    = "content_prefix_kind_kwd"
	prefixVersionField = "content_prefix_version_int"
	prefixCharsField   = "content_prefix_chars_int"
	prefixHashField    = "content_prefix_hash_kwd"

	// prefixNone and an absent field mean "no prefix was recorded here", which is the
	// truthful answer for legacy chunks and for content a human edited.
	prefixNone           = "none"
	prefixKindLegacy     = "identity_legacy"
	prefixKindProfile    = "identity_profile"
	legacyPrefixVersion  = 1
	profilePrefixVersion = 2
)

// prefixHash is the hash a consumer verifies: xxhash64, sixteen lowercase hex characters,
// over the UTF-8 bytes of the injected prefix. It is the SAME algorithm and encoding the
// Python producer uses (`xxhash.xxh64(prefix.encode("utf-8")).hexdigest()`), so a chunk
// written by either backend verifies in the other.
func prefixHash(prefix string) string {
	return fmt.Sprintf("%016x", xxhash.Sum64String(prefix))
}

// recordPrefix records that prefix was injected at position 0 of this chunk's content.
// It is called by the producer immediately after it prepends, never by a reader: the
// extent is what the producer WROTE, which is the only way to know where a prefix ends.
func recordPrefix(chunk map[string]any, prefix, kind string, version int) {
	// Code points, not bytes: len([]rune(...)) matches Python's len(str), and a multi-byte
	// title must not shift the boundary.
	extent := len([]rune(prefix))
	chunk[prefixKindField] = kind
	chunk[prefixVersionField] = version
	chunk[prefixCharsField] = extent
	if extent == 0 {
		chunk[prefixHashField] = ""
		return
	}
	chunk[prefixHashField] = prefixHash(prefix)
}

// clearPrefix states that this chunk has no recorded prefix.
func clearPrefix(chunk map[string]any) {
	chunk[prefixKindField] = prefixNone
	chunk[prefixVersionField] = 0
	chunk[prefixCharsField] = 0
	chunk[prefixHashField] = ""
}

// prefixContent is the text the extent indexes. The stored representation is
// content_with_weight (the same key the Python consumer reads); during chunk assembly the
// same text is still under `text`.
func prefixContent(chunk map[string]any) (string, bool) {
	if content, ok := chunk["content_with_weight"].(string); ok {
		return content, true
	}
	if text, ok := chunk["text"].(string); ok {
		return text, true
	}
	return "", false
}

// toInt accepts the shapes a chunk value can arrive in (written here as int, read back
// from a document store as a float or a JSON number).
func toInt(value any) (int, bool) {
	switch typed := value.(type) {
	case int:
		return typed, true
	case int32:
		return int(typed), true
	case int64:
		return int(typed), true
	case float64:
		if typed != float64(int(typed)) {
			return 0, false
		}
		return int(typed), true
	default:
		return 0, false
	}
}

// verifiedPrefixExtent returns the extent of the injected prefix, or nil when it cannot be
// PROVEN. The invariant: a kind other than none, an integer extent in range, and a hash of
// content[:extent] that matches what the producer recorded. Anything else - missing
// fields, a wrong extent, an unknown kind, one byte changed anywhere - is nil, and the
// caller must then treat the whole content as the passage's text.
func verifiedPrefixExtent(chunk map[string]any) *int {
	kind, _ := chunk[prefixKindField].(string)
	if kind == "" || kind == prefixNone {
		return nil
	}
	extent, ok := toInt(chunk[prefixCharsField])
	if !ok || extent <= 0 {
		return nil
	}
	content, ok := prefixContent(chunk)
	if !ok || extent > len([]rune(content)) {
		return nil
	}
	digest, _ := chunk[prefixHashField].(string)
	if digest == "" {
		return nil
	}
	if prefixHash(string([]rune(content)[:extent])) != digest {
		return nil
	}
	return &extent
}

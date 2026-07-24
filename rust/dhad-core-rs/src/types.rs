//! Core value types shared by every layer of the portable engine.
//!
//! These mirror the Python reference types field-for-field
//! (`dhad.text.Token`, `dhad.text.Sentence`, `dhad.match.Match`) so that a
//! serialized value from either implementation is readable by the other.
//! All offsets are **Unicode scalar (char) offsets**, matching Python string
//! indexing, never UTF-8 byte offsets.

/// Token classification, identical to `dhad.text.TokenKind`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TokenKind {
    ArabicWord,
    LatinWord,
    Number,
    Url,
    Email,
    Hashtag,
    Mention,
    Code,
    Punctuation,
    Symbol,
    Whitespace,
}

impl TokenKind {
    /// The wire name used by the Python reference implementation.
    pub fn as_str(self) -> &'static str {
        match self {
            TokenKind::ArabicWord => "arabic_word",
            TokenKind::LatinWord => "latin_word",
            TokenKind::Number => "number",
            TokenKind::Url => "url",
            TokenKind::Email => "email",
            TokenKind::Hashtag => "hashtag",
            TokenKind::Mention => "mention",
            TokenKind::Code => "code",
            TokenKind::Punctuation => "punctuation",
            TokenKind::Symbol => "symbol",
            TokenKind::Whitespace => "whitespace",
        }
    }
}

/// A token whose `start`/`end` are char offsets into the original input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token {
    pub text: String,
    pub start: usize,
    pub end: usize,
    pub kind: TokenKind,
}

impl Token {
    pub fn is_arabic(&self) -> bool {
        self.kind == TokenKind::ArabicWord
    }

    pub fn is_word(&self) -> bool {
        matches!(
            self.kind,
            TokenKind::ArabicWord | TokenKind::LatinWord | TokenKind::Hashtag | TokenKind::Mention
        )
    }
}

/// A sentence-like unit with a stable char span in the source text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sentence {
    pub text: String,
    pub start: usize,
    pub end: usize,
    /// The terminator run (and trailing closers) that followed the body.
    pub terminator: String,
}

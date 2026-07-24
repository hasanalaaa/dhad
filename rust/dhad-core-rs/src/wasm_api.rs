#![deny(unsafe_op_in_unsafe_fn)]

//! Hand-rolled WASM ABI — no wasm-bindgen or generated glue.
//!
//! The diagnostic hot path is a persistent-document, packed binary ABI. JS
//! encodes UTF-8 directly into a reusable allocation, updates a generation-
//! safe document handle, and reads the document-owned result in place through
//! `DataView`/`Uint8Array`. No JSON serialization, response copy, or output
//! `dc_free` occurs on that path. See `packed.rs` and `web_demo/dhad-core.js`
//! for the version-1 table layout and its view-lifetime enforcement.
//!
//! Contract (see `web_demo/dhad-core.js` for the JS side):
//!
//! * `dc_alloc(len) -> ptr` / `dc_free(ptr, len)` — buffer management.
//! * `dc_load_rules(ptr, len) -> loaded_rule_count | -1` — install a rule
//!   pack (JSON from `tools/export_wasm_rules.py`) into the engine.
//! * `dc_doc_create` / `dc_doc_update` / `dc_doc_destroy` — explicit document
//!   ownership with stale-handle rejection.
//! * `dc_doc_analyze` + `dc_doc_result_ptr/len` — document-owned packed raw
//!   and resolved diagnostics; valid until update/analyze/destroy.
//! * `dc_check(ptr, len) -> packed` — compatibility JSON diagnostic API used
//!   only by the same-binary Phase-2 A/B benchmark.
//! * `dc_tokenize(ptr, len) -> packed` — JSON token stream (lossless).
//! * `dc_sentences(ptr, len) -> packed` — JSON sentence spans.
//! * `dc_normalize(mode, ptr, len) -> packed` — normalized text (mode:
//!   0 strict, 1 lookup, 2 search, 3 aggressive).
//! * `dc_analyze(ptr, len, min_confidence) -> packed` — complete ranked
//!   morphology analyses from the embedded lexicon and pattern engine.
//! * `dc_parse(ptr, len) -> packed` — morphology-selected syntax relations
//!   and candidate i'rab for every sentence.
//! * `dc_syntax_check(ptr, len) -> packed` — morphology-aware deterministic
//!   grammar matches only.
//!
//! Every entry point is safe against invalid UTF-8 (lossy decode) and a
//! missing rule pack (returns an error JSON instead of trapping).

use std::cell::RefCell;

use crate::packed::encode_diagnostics;
use crate::rules::RuleSet;
use crate::spans::{dedupe, dedupe_indices};
use crate::text::{normalize, sentence_spans, tokenize_all, NormalizationMode};
use crate::{morphology::default_lexicon, MorphologicalAnalyzer, SyntaxEngine};

thread_local! {
    static RULES: RefCell<Option<RuleSet>> = const { RefCell::new(None) };
    static DOCUMENTS: RefCell<DocumentStore> = RefCell::new(DocumentStore::default());
}

const HANDLE_SLOT_BITS: u32 = 20;
const HANDLE_SLOT_MASK: u32 = (1 << HANDLE_SLOT_BITS) - 1;
const HANDLE_GENERATION_MASK: u32 = (1 << (32 - HANDLE_SLOT_BITS)) - 1;

struct Document {
    text: String,
    packed_diagnostics: Vec<u8>,
    revision: u32,
}

struct DocumentSlot {
    generation: u32,
    document: Option<Document>,
}

#[derive(Default)]
struct DocumentStore {
    slots: Vec<DocumentSlot>,
    free: Vec<usize>,
    live: usize,
}

impl DocumentStore {
    fn create(&mut self, text: String) -> Option<u32> {
        let document = Document {
            text,
            packed_diagnostics: Vec::new(),
            revision: 1,
        };
        let index = if let Some(index) = self.free.pop() {
            self.slots[index].document = Some(document);
            index
        } else {
            if self.slots.len() >= HANDLE_SLOT_MASK as usize {
                return None;
            }
            let index = self.slots.len();
            self.slots.push(DocumentSlot {
                generation: 1,
                document: Some(document),
            });
            index
        };
        self.live += 1;
        Some(Self::encode_handle(index, self.slots[index].generation))
    }

    fn decode_handle(handle: u32) -> Option<(usize, u32)> {
        let encoded_slot = handle & HANDLE_SLOT_MASK;
        let generation = handle >> HANDLE_SLOT_BITS;
        if encoded_slot == 0 || generation == 0 {
            return None;
        }
        Some(((encoded_slot - 1) as usize, generation))
    }

    fn encode_handle(index: usize, generation: u32) -> u32 {
        (generation << HANDLE_SLOT_BITS) | (index as u32 + 1)
    }

    fn get(&self, handle: u32) -> Option<&Document> {
        let (index, generation) = Self::decode_handle(handle)?;
        let slot = self.slots.get(index)?;
        if slot.generation != generation {
            return None;
        }
        slot.document.as_ref()
    }

    fn get_mut(&mut self, handle: u32) -> Option<&mut Document> {
        let (index, generation) = Self::decode_handle(handle)?;
        let slot = self.slots.get_mut(index)?;
        if slot.generation != generation {
            return None;
        }
        slot.document.as_mut()
    }

    fn destroy(&mut self, handle: u32) -> bool {
        let Some((index, generation)) = Self::decode_handle(handle) else {
            return false;
        };
        let Some(slot) = self.slots.get_mut(index) else {
            return false;
        };
        if slot.generation != generation || slot.document.take().is_none() {
            return false;
        }
        if slot.generation < HANDLE_GENERATION_MASK {
            slot.generation += 1;
            self.free.push(index);
        }
        self.live -= 1;
        true
    }
}

unsafe fn read_utf8<'a>(ptr: *const u8, len: usize) -> Result<&'a str, ()> {
    if len == 0 {
        return Ok("");
    }
    if ptr.is_null() {
        return Err(());
    }
    // SAFETY: the caller guarantees that `ptr` addresses `len` readable bytes.
    let input = unsafe { std::slice::from_raw_parts(ptr, len) };
    std::str::from_utf8(input).map_err(|_| ())
}

/// Number of currently live persistent documents in this thread.
#[no_mangle]
pub extern "C" fn dc_live_documents() -> usize {
    DOCUMENTS.with(|cell| cell.borrow().live)
}

/// Create a persistent UTF-8 document. Returns zero on invalid UTF-8 or when
/// the generation-safe handle table is exhausted.
///
/// # Safety
/// `ptr` must address `len` readable bytes for the duration of the call.
#[no_mangle]
pub unsafe extern "C" fn dc_doc_create(ptr: *const u8, len: usize) -> u32 {
    let Ok(text) = (unsafe { read_utf8(ptr, len) }) else {
        return 0;
    };
    DOCUMENTS.with(|cell| cell.borrow_mut().create(text.to_owned()).unwrap_or(0))
}

/// Replace a persistent document's contents, retaining its result capacity.
/// Returns `0` on success, `-1` for a stale handle, or `-2` for invalid UTF-8.
///
/// # Safety
/// `ptr` must address `len` readable bytes for the duration of the call.
#[no_mangle]
pub unsafe extern "C" fn dc_doc_update(handle: u32, ptr: *const u8, len: usize) -> i32 {
    let Ok(text) = (unsafe { read_utf8(ptr, len) }) else {
        return -2;
    };
    DOCUMENTS.with(|cell| {
        let mut documents = cell.borrow_mut();
        let Some(document) = documents.get_mut(handle) else {
            return -1;
        };
        document.text.clear();
        document.text.push_str(text);
        document.packed_diagnostics.clear();
        document.revision = document.revision.wrapping_add(1).max(1);
        0
    })
}

/// Analyze a persistent document into its reusable packed diagnostics buffer.
/// Returns `0` on success, `-1` for a stale handle, `-2` when no rule pack is
/// loaded, or `-3` if the version-1 packed ABI limits are exceeded.
#[no_mangle]
pub extern "C" fn dc_doc_analyze(handle: u32) -> i32 {
    RULES.with(|rules_cell| {
        let rules = rules_cell.borrow();
        let Some(rules) = rules.as_ref() else {
            return -2;
        };
        DOCUMENTS.with(|documents_cell| {
            let mut documents = documents_cell.borrow_mut();
            let Some(document) = documents.get_mut(handle) else {
                return -1;
            };
            let mut matches = rules.check(&document.text);
            matches.extend(SyntaxEngine::default().check_text(&document.text));
            let resolved = dedupe_indices(&matches);
            if encode_diagnostics(
                &matches,
                &resolved,
                document.revision,
                &mut document.packed_diagnostics,
            )
            .is_err()
            {
                document.packed_diagnostics.clear();
                return -3;
            }
            0
        })
    })
}

/// Pointer to the document-owned packed result. The view remains valid until
/// the next update, analysis, or destruction of this document (and until WASM
/// linear memory grows). Returns null for stale or not-yet-analyzed documents.
#[no_mangle]
pub extern "C" fn dc_doc_result_ptr(handle: u32) -> *const u8 {
    DOCUMENTS.with(|cell| {
        cell.borrow()
            .get(handle)
            .map_or(std::ptr::null(), |document| {
                if document.packed_diagnostics.is_empty() {
                    std::ptr::null()
                } else {
                    document.packed_diagnostics.as_ptr()
                }
            })
    })
}

#[no_mangle]
pub extern "C" fn dc_doc_result_len(handle: u32) -> usize {
    DOCUMENTS.with(|cell| {
        cell.borrow()
            .get(handle)
            .map_or(0, |document| document.packed_diagnostics.len())
    })
}

#[no_mangle]
pub extern "C" fn dc_doc_revision(handle: u32) -> u32 {
    DOCUMENTS.with(|cell| {
        cell.borrow()
            .get(handle)
            .map_or(0, |document| document.revision)
    })
}

/// Destroy a persistent document. Returns one if it was live, otherwise zero.
#[no_mangle]
pub extern "C" fn dc_doc_destroy(handle: u32) -> i32 {
    DOCUMENTS.with(|cell| i32::from(cell.borrow_mut().destroy(handle)))
}

/// Eagerly initialize the embedded morphology indexes during engine loading so
/// the first interactive check does not pay the one-time lexicon cost.
#[no_mangle]
pub extern "C" fn dc_warmup() -> usize {
    default_lexicon().lexemes.len()
}

/// # Safety
/// Returns a buffer of exactly `len` bytes owned by the caller; release it
/// with [`dc_free`].
#[no_mangle]
pub extern "C" fn dc_alloc(len: usize) -> *mut u8 {
    let mut buffer = Vec::<u8>::with_capacity(len.max(1));
    let ptr = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    ptr
}

/// # Safety
/// `ptr` must originate from [`dc_alloc`] or a packed return value, with the
/// matching `len`.
#[no_mangle]
pub unsafe extern "C" fn dc_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() {
        // SAFETY: the function contract requires an allocation returned by
        // `dc_alloc` (or the equivalent packed response allocation).
        drop(unsafe { Vec::from_raw_parts(ptr, 0, len.max(1)) });
    }
}

unsafe fn read_input(ptr: *const u8, len: usize) -> String {
    if ptr.is_null() || len == 0 {
        return String::new();
    }
    // SAFETY: the caller guarantees that `ptr` addresses `len` readable bytes.
    let bytes = unsafe { std::slice::from_raw_parts(ptr, len) };
    String::from_utf8_lossy(bytes).into_owned()
}

fn pack_response(payload: String) -> u64 {
    let bytes = payload.into_bytes();
    let len = bytes.len();
    let ptr = dc_alloc(len);
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr, len);
    }
    ((ptr as u64) << 32) | (len as u64)
}

#[no_mangle]
/// Load a serialized rule pack into the thread-local engine.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_load_rules(ptr: *const u8, len: usize) -> i64 {
    let payload = unsafe { read_input(ptr, len) };
    match RuleSet::from_json(&payload) {
        Ok(rules) => {
            let count = rules.len() as i64;
            RULES.with(|cell| *cell.borrow_mut() = Some(rules));
            count
        }
        Err(_) => -1,
    }
}

#[no_mangle]
/// Run the loaded rule pack and syntax checks over UTF-8 input.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_check(ptr: *const u8, len: usize) -> u64 {
    let text = unsafe { read_input(ptr, len) };
    let response = RULES.with(|cell| match &*cell.borrow() {
        Some(rules) => {
            let mut matches = rules.check(&text);
            matches.extend(SyntaxEngine::default().check_text(&text));
            let resolved = dedupe(matches.clone());
            serde_json::json!({ "matches": matches, "resolved": resolved }).to_string()
        }
        None => serde_json::json!({ "error": "no rule pack loaded" }).to_string(),
    });
    pack_response(response)
}

#[no_mangle]
/// Analyze one UTF-8 token morphologically.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_analyze(ptr: *const u8, len: usize, min_confidence: f64) -> u64 {
    let token = unsafe { read_input(ptr, len) };
    let response = match MorphologicalAnalyzer::default().analyze(&token, min_confidence) {
        Ok(analyses) => serde_json::json!({ "analyses": analyses }).to_string(),
        Err(error) => serde_json::json!({ "error": error }).to_string(),
    };
    pack_response(response)
}

#[no_mangle]
/// Parse a UTF-8 document into the portable syntax representation.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_parse(ptr: *const u8, len: usize) -> u64 {
    let text = unsafe { read_input(ptr, len) };
    pack_response(
        serde_json::to_string(&SyntaxEngine::default().parse(&text))
            .expect("syntax parse is serializable"),
    )
}

#[no_mangle]
/// Run syntax diagnostics over a UTF-8 document.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_syntax_check(ptr: *const u8, len: usize) -> u64 {
    let text = unsafe { read_input(ptr, len) };
    pack_response(
        serde_json::json!({ "matches": SyntaxEngine::default().check_text(&text) }).to_string(),
    )
}

#[no_mangle]
/// Tokenize a UTF-8 document.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_tokenize(ptr: *const u8, len: usize) -> u64 {
    let text = unsafe { read_input(ptr, len) };
    let tokens: Vec<_> = tokenize_all(&text)
        .into_iter()
        .map(|token| {
            serde_json::json!({
                "text": token.text,
                "start": token.start,
                "end": token.end,
                "kind": token.kind.as_str(),
            })
        })
        .collect();
    pack_response(serde_json::json!({ "tokens": tokens }).to_string())
}

#[no_mangle]
/// Segment a UTF-8 document into sentences.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_sentences(ptr: *const u8, len: usize) -> u64 {
    let text = unsafe { read_input(ptr, len) };
    let sentences: Vec<_> = sentence_spans(&text)
        .into_iter()
        .map(|sentence| {
            serde_json::json!({
                "text": sentence.text,
                "start": sentence.start,
                "end": sentence.end,
                "terminator": sentence.terminator,
            })
        })
        .collect();
    pack_response(serde_json::json!({ "sentences": sentences }).to_string())
}

#[no_mangle]
/// Normalize UTF-8 input according to the selected policy.
///
/// # Safety
/// `ptr` must address `len` readable bytes in this module's linear memory for
/// the duration of the call. A null pointer is valid only when `len == 0`.
pub unsafe extern "C" fn dc_normalize(mode: u32, ptr: *const u8, len: usize) -> u64 {
    let text = unsafe { read_input(ptr, len) };
    let policy = match mode {
        0 => NormalizationMode::Strict,
        1 => NormalizationMode::Lookup,
        2 => NormalizationMode::Search,
        _ => NormalizationMode::Aggressive,
    };
    pack_response(serde_json::json!({ "normalized": normalize(&text, policy) }).to_string())
}

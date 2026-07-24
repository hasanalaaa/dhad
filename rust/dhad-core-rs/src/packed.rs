//! Versioned packed diagnostics ABI shared by Rust/WASM and JavaScript.
//!
//! All integers are little-endian. Records reference an interned UTF-8 string
//! table and string-list table, so no JSON encoder or output allocation is
//! needed at the JavaScript boundary. The owning document keeps the resulting
//! `Vec<u8>` alive until its next update, analysis, or destruction.

use std::collections::HashMap;

use crate::rules::RuleMatch;

pub const MAGIC: u32 = 0x4441_4844; // bytes: "DHAD"
pub const FORMAT_VERSION: u16 = 1;
pub const HEADER_SIZE: usize = 56;
pub const RECORD_SIZE: usize = 80;
pub const LIST_ENTRY_SIZE: usize = 8;

#[derive(Clone, Copy)]
struct StringRef {
    offset: u32,
    length: u32,
}

struct PackedRecord {
    rule_id: StringRef,
    category: StringRef,
    message: StringRef,
    explanation: StringRef,
    offset: u32,
    length: u32,
    confidence: f64,
    priority: i32,
    replacements_start: u32,
    tags_start: u32,
    references_start: u32,
    profiles_start: u32,
    replacements_count: u16,
    tags_count: u16,
    references_count: u16,
    profiles_count: u16,
    severity: u8,
    autofix: u8,
}

struct Encoder<'a> {
    strings: Vec<u8>,
    interned: HashMap<&'a str, StringRef>,
    lists: Vec<StringRef>,
    records: Vec<PackedRecord>,
}

impl<'a> Encoder<'a> {
    fn new(record_count: usize) -> Self {
        Self {
            strings: Vec::new(),
            interned: HashMap::new(),
            lists: Vec::new(),
            records: Vec::with_capacity(record_count),
        }
    }

    fn string(&mut self, value: &'a str) -> Result<StringRef, ()> {
        if let Some(reference) = self.interned.get(value) {
            return Ok(*reference);
        }
        let reference = StringRef {
            offset: u32::try_from(self.strings.len()).map_err(|_| ())?,
            length: u32::try_from(value.len()).map_err(|_| ())?,
        };
        self.strings.extend_from_slice(value.as_bytes());
        self.interned.insert(value, reference);
        Ok(reference)
    }

    fn list(&mut self, values: &'a [String]) -> Result<(u32, u16), ()> {
        let start = u32::try_from(self.lists.len()).map_err(|_| ())?;
        let count = u16::try_from(values.len()).map_err(|_| ())?;
        for value in values {
            let reference = self.string(value)?;
            self.lists.push(reference);
        }
        Ok((start, count))
    }

    fn record(&mut self, item: &'a RuleMatch) -> Result<(), ()> {
        let rule_id = self.string(&item.rule_id)?;
        let category = self.string(&item.category)?;
        let message = self.string(&item.message)?;
        let explanation = self.string(&item.explanation)?;
        let (replacements_start, replacements_count) = self.list(&item.replacements)?;
        let (tags_start, tags_count) = self.list(&item.tags)?;
        let (references_start, references_count) = self.list(&item.references)?;
        let (profiles_start, profiles_count) = self.list(&item.profiles)?;
        self.records.push(PackedRecord {
            rule_id,
            category,
            message,
            explanation,
            offset: u32::try_from(item.offset).map_err(|_| ())?,
            length: u32::try_from(item.length).map_err(|_| ())?,
            confidence: item.confidence,
            priority: item.priority,
            replacements_start,
            tags_start,
            references_start,
            profiles_start,
            replacements_count,
            tags_count,
            references_count,
            profiles_count,
            severity: match item.severity.as_str() {
                "error" => 2,
                "warning" => 1,
                _ => 0,
            },
            autofix: u8::from(item.autofix),
        });
        Ok(())
    }
}

fn put_u16(output: &mut [u8], offset: usize, value: u16) {
    output[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

fn put_u32(output: &mut [u8], offset: usize, value: u32) {
    output[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn put_i32(output: &mut [u8], offset: usize, value: i32) {
    output[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn write_string_ref(output: &mut [u8], offset: usize, reference: StringRef) {
    put_u32(output, offset, reference.offset);
    put_u32(output, offset + 4, reference.length);
}

/// Encode raw diagnostics followed by resolved winner records into `output`.
/// Existing capacity is retained and reused by persistent document handles.
pub fn encode_diagnostics(
    raw: &[RuleMatch],
    resolved: &[usize],
    revision: u32,
    output: &mut Vec<u8>,
) -> Result<(), ()> {
    let record_count = raw.len().checked_add(resolved.len()).ok_or(())?;
    let mut encoder = Encoder::new(record_count);
    for item in raw {
        encoder.record(item)?;
    }
    for index in resolved {
        encoder.record(raw.get(*index).ok_or(())?)?;
    }

    let records_bytes = encoder.records.len().checked_mul(RECORD_SIZE).ok_or(())?;
    let lists_bytes = encoder.lists.len().checked_mul(LIST_ENTRY_SIZE).ok_or(())?;
    let lists_offset = HEADER_SIZE.checked_add(records_bytes).ok_or(())?;
    let strings_offset = lists_offset.checked_add(lists_bytes).ok_or(())?;
    let total_len = strings_offset
        .checked_add(encoder.strings.len())
        .ok_or(())?;
    let total_len_u32 = u32::try_from(total_len).map_err(|_| ())?;

    output.clear();
    output.resize(total_len, 0);
    put_u32(output, 0, MAGIC);
    put_u16(output, 4, FORMAT_VERSION);
    put_u16(output, 6, HEADER_SIZE as u16);
    put_u16(output, 8, RECORD_SIZE as u16);
    put_u16(output, 10, LIST_ENTRY_SIZE as u16);
    put_u32(output, 12, 0);
    put_u32(output, 16, u32::try_from(raw.len()).map_err(|_| ())?);
    put_u32(output, 20, u32::try_from(resolved.len()).map_err(|_| ())?);
    put_u32(output, 24, u32::try_from(record_count).map_err(|_| ())?);
    put_u32(
        output,
        28,
        u32::try_from(encoder.lists.len()).map_err(|_| ())?,
    );
    put_u32(output, 32, HEADER_SIZE as u32);
    put_u32(output, 36, u32::try_from(lists_offset).map_err(|_| ())?);
    put_u32(output, 40, u32::try_from(strings_offset).map_err(|_| ())?);
    put_u32(
        output,
        44,
        u32::try_from(encoder.strings.len()).map_err(|_| ())?,
    );
    put_u32(output, 48, total_len_u32);
    put_u32(output, 52, revision);

    for (index, record) in encoder.records.iter().enumerate() {
        let base = HEADER_SIZE + index * RECORD_SIZE;
        write_string_ref(output, base, record.rule_id);
        write_string_ref(output, base + 8, record.category);
        write_string_ref(output, base + 16, record.message);
        write_string_ref(output, base + 24, record.explanation);
        put_u32(output, base + 32, record.offset);
        put_u32(output, base + 36, record.length);
        output[base + 40..base + 48].copy_from_slice(&record.confidence.to_le_bytes());
        put_i32(output, base + 48, record.priority);
        put_u32(output, base + 52, record.replacements_start);
        put_u32(output, base + 56, record.tags_start);
        put_u32(output, base + 60, record.references_start);
        put_u32(output, base + 64, record.profiles_start);
        put_u16(output, base + 68, record.replacements_count);
        put_u16(output, base + 70, record.tags_count);
        put_u16(output, base + 72, record.references_count);
        put_u16(output, base + 74, record.profiles_count);
        output[base + 76] = record.severity;
        output[base + 77] = record.autofix;
    }

    for (index, reference) in encoder.lists.iter().enumerate() {
        write_string_ref(output, lists_offset + index * LIST_ENTRY_SIZE, *reference);
    }
    output[strings_offset..].copy_from_slice(&encoder.strings);
    Ok(())
}
